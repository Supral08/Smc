#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import signal
import time
import asyncio
import json
import websockets
import pandas as pd
import numpy as np
from datetime import datetime
from telegram import Bot
from telegram.ext import Application, CommandHandler

# ============================================================
# GESTION DES CONFLITS
# ============================================================

PID_FILE = "bot.pid"

def verifier_instance_unique():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            print(f"⚠️ Instance existante (PID: {old_pid})")
            os.kill(old_pid, signal.SIGTERM)
            time.sleep(2)
        except (OSError, ValueError):
            pass
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    print(f"✅ Instance unique (PID: {os.getpid()})")

def nettoyer_pid():
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except:
        pass

# ============================================================
# CONFIGURATION
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = int(os.environ.get("CHAT_ID", 0))

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("TELEGRAM_TOKEN et CHAT_ID doivent être définis dans les variables d'environnement")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
SCAN_INTERVAL = 60

# ============================================================
# WEBSOCKET BYBIT (PAS DE REQUÊTES HTTP)
# ============================================================

class BybitWebSocket:
    def __init__(self):
        self.prices = {}
        self.last_update = None
        self.connected = False
        self.ws = None
    
    async def connect(self):
        """Connecte au WebSocket Bybit"""
        try:
            uri = "wss://stream.bybit.com/v5/public/linear"
            self.ws = await websockets.connect(uri, ping_interval=20, ping_timeout=10)
            self.connected = True
            print("✅ WebSocket Bybit connecté")
            
            # S'abonner aux symboles
            for symbol in SYMBOLS:
                sub = {
                    "op": "subscribe",
                    "args": [f"tickers.{symbol}"]
                }
                await self.ws.send(json.dumps(sub))
                print(f"📊 Abonné à {symbol}")
            
            # Lancer la réception des messages
            asyncio.create_task(self.receive_messages())
            
        except Exception as e:
            print(f"❌ Erreur WebSocket: {e}")
            self.connected = False
    
    async def receive_messages(self):
        """Reçoit les messages du WebSocket"""
        try:
            async for message in self.ws:
                data = json.loads(message)
                if "data" in data and "topic" in data and "tickers" in data["topic"]:
                    ticker = data["data"]
                    symbol = ticker["symbol"]
                    self.prices[symbol] = {
                        "price": float(ticker["lastPrice"]),
                        "high_24h": float(ticker["highPrice24h"]),
                        "low_24h": float(ticker["lowPrice24h"])
                    }
                    self.last_update = datetime.now()
                    print(f"📊 {symbol}: ${float(ticker['lastPrice']):.2f}")
        except Exception as e:
            print(f"❌ Erreur réception: {e}")
            self.connected = False
            await self.reconnect()
    
    async def reconnect(self):
        """Reconnecte en cas de déconnexion"""
        print("🔄 Reconnexion WebSocket...")
        await asyncio.sleep(5)
        await self.connect()
    
    def get_price(self, symbol="BTCUSDT"):
        """Récupère le prix depuis le cache WebSocket"""
        if symbol in self.prices:
            return {
                "symbol": symbol,
                "price": self.prices[symbol]["price"],
                "high_24h": self.prices[symbol]["high_24h"],
                "low_24h": self.prices[symbol]["low_24h"]
            }
        return None
    
    def get_all_prices(self):
        """Récupère tous les prix"""
        return self.prices

# ============================================================
# ANALYSE SMC
# ============================================================

class AnalyseSMC:
    def __init__(self, ws):
        self.ws = ws
    
    def analyser(self, symbol, zone_touchee):
        # Utiliser les données du WebSocket
        data = self.ws.get_price(symbol)
        if not data:
            return {
                "verdict": "OBSERVATION_EN_COURS",
                "justification": "Données WebSocket indisponibles",
                "prix": 0
            }
        
        prix = data["price"]
        
        # Analyse simplifiée pour le test
        sweep = self.detecter_sweep(data, zone_touchee)
        mss = {"mss_requis": False}
        displacement = {"confirme": False}
        pullback = {"confirme": False}
        verdict = self.evaluer_setup(sweep, mss, displacement, pullback)
        
        return {
            "symbol": symbol,
            "prix": round(prix, 2),
            "zone": zone_touchee,
            "sweep": sweep,
            "mss": mss,
            "displacement": displacement,
            "pullback": pullback,
            "macd": {"croisement": "INCONNU"},
            "dominance": {"dominant": "Neutre"},
            "sar": {"prix_vs_sar": "INCONNU"},
            "verdict": verdict
        }
    
    def detecter_sweep(self, data, zone):
        """Détecte un sweep basé sur les données WebSocket"""
        niveau = zone["niveau"]
        prix = data["price"]
        
        if zone["zone"] == "24h_high":
            if prix < niveau:
                return {"type": "SELL", "confirme": True}
            return {"type": "SELL", "confirme": False}
        elif zone["zone"] == "24h_low":
            if prix > niveau:
                return {"type": "BUY", "confirme": True}
            return {"type": "BUY", "confirme": False}
        return {"type": None, "confirme": False}
    
    def evaluer_setup(self, sweep, mss, displacement, pullback):
        conditions = {
            "sweep": sweep["confirme"],
            "mss_requis": mss["mss_requis"],
            "displacement": displacement["confirme"],
            "pullback": pullback["confirme"]
        }
        if all(conditions.values()):
            return {
                "verdict": "SETUP_A+",
                "direction": sweep["type"],
                "conditions": conditions,
                "justification": f"Sweep {sweep['type']} ✅ | MSS ✅ | Displacement ✅ | Pullback ✅"
            }
        else:
            manquants = [k for k, v in conditions.items() if not v]
            return {
                "verdict": "OBSERVATION_EN_COURS",
                "direction": None,
                "conditions": conditions,
                "justification": f"Manque: {', '.join(manquants)}"
            }

# ============================================================
# BOT TELEGRAM
# ============================================================

class TradingBot:
    def __init__(self, token, chat_id, ws):
        self.token = token
        self.chat_id = chat_id
        self.bot = Bot(token=token)
        self.ws = ws
        self.analyse = AnalyseSMC(ws)
        self.dernieres_zones = {}
        self.scan_en_cours = False
    
    async def start(self, update, context):
        await update.message.reply_text(
            "🤖 **Bot SMC Trading (WebSocket)**\n\n"
            "📊 **Commandes :**\n"
            "/start - Démarrer\n"
            "/price - Prix en direct\n"
            "/scan - Scan manuel\n"
            "/status - État du bot\n"
            "/ping - Test de connexion\n"
            "/help - Aide",
            parse_mode="Markdown"
        )
    
    async def price(self, update, context):
        await update.message.reply_text("📊 Récupération des prix...")
        
        message = "💰 **Prix en direct (WebSocket Bybit) :**\n\n"
        
        if not self.ws.prices:
            message += "⏳ En attente des données WebSocket...\n"
            message += "🔄 Connexion en cours..."
        else:
            for symbol in SYMBOLS:
                data = self.ws.get_price(symbol)
                if data:
                    message += f"• **{symbol}** : ${data['price']:.2f}\n"
                    message += f"  (24h H: ${data['high_24h']:.2f} / L: ${data['low_24h']:.2f})\n\n"
                else:
                    message += f"• **{symbol}** : ❌ En attente\n\n"
        
        if self.ws.last_update:
            message += f"🕐 Mis à jour : {self.ws.last_update.strftime('%H:%M:%S')} UTC"
        else:
            message += "🕐 Mis à jour : En attente de la première donnée..."
        
        await update.message.reply_text(message, parse_mode="Markdown")
    
    async def ping(self, update, context):
        connected = "✅" if self.ws.connected else "🔄"
        status = "Connecté" if self.ws.connected else "Connexion en cours..."
        nb_prices = len(self.ws.prices)
        
        await update.message.reply_text(
            f"🏓 **Pong !**\n\n"
            f"✅ Bot connecté\n"
            f"{connected} WebSocket : {status}\n"
            f"📊 Prix reçus : {nb_prices}/{len(SYMBOLS)}\n"
            f"⏰ Heure : {datetime.now().strftime('%H:%M:%S')}\n"
            f"📊 Symboles : {', '.join(SYMBOLS)}",
            parse_mode="Markdown"
        )
    
    async def help(self, update, context):
        await update.message.reply_text(
            "🤖 **Aide**\n\n"
            "• Connexion WebSocket Bybit\n"
            "• Scan des liquidités (24h High/Low)\n"
            "• Analyse SMC (Sweep, MSS, Displacement, Pullback)\n"
            "• Alerte si SETUP A+ détecté\n\n"
            "Commandes : /start, /price, /scan, /status, /ping, /help",
            parse_mode="Markdown"
        )
    
    async def status(self, update, context):
        connected = "✅" if self.ws.connected else "🔄"
        nb_prices = len(self.ws.prices)
        
        await update.message.reply_text(
            f"📊 **État du bot**\n"
            f"• Symboles : {', '.join(SYMBOLS)}\n"
            f"• WebSocket : {connected}\n"
            f"• Prix reçus : {nb_prices}/{len(SYMBOLS)}\n"
            f"• Intervalle : {SCAN_INTERVAL}s\n"
            f"• Heure : {datetime.now().strftime('%H:%M:%S')}",
            parse_mode="Markdown"
        )
    
    async def scan(self, update, context):
        if self.scan_en_cours:
            await update.message.reply_text("⏳ Scan en cours...")
            return
        
        await update.message.reply_text("🔍 Scan manuel en cours...")
        await self.scanner()
        await update.message.reply_text("✅ Scan terminé !")
    
    async def scanner(self):
        if self.scan_en_cours:
            return
        
        self.scan_en_cours = True
        print(f"\n🔍 [{datetime.now().strftime('%H:%M:%S')}] Scan...")
        
        for symbol in SYMBOLS:
            data = self.ws.get_price(symbol)
            if not data:
                print(f"❌ {symbol}: En attente des données")
                continue
            
            prix = data["price"]
            high = data["high_24h"]
            low = data["low_24h"]
            
            print(f"   📊 {symbol}: {prix:.2f} (H:{high:.2f} L:{low:.2f})")
            
            if symbol not in self.dernieres_zones:
                self.dernieres_zones[symbol] = None
            
            zone_touchee = None
            
            if prix >= high:
                if self.dernieres_zones[symbol] != "24h_high":
                    zone_touchee = {"zone": "24h_high", "niveau": high}
                    self.dernieres_zones[symbol] = "24h_high"
                    print(f"🔔 {symbol} - 24h HIGH touchée !")
                    await self.envoyer_alerte(symbol, zone_touchee, prix)
            elif prix <= low:
                if self.dernieres_zones[symbol] != "24h_low":
                    zone_touchee = {"zone": "24h_low", "niveau": low}
                    self.dernieres_zones[symbol] = "24h_low"
                    print(f"🔔 {symbol} - 24h LOW touchée !")
                    await self.envoyer_alerte(symbol, zone_touchee, prix)
        
        self.scan_en_cours = False
    
    async def envoyer_alerte(self, symbol, zone, prix):
        niveau = zone["niveau"]
        
        msg = f"""
🔔 **LIQUIDITÉ TOUCHÉE !**

📊 **Actif :** {symbol}
📍 **Zone :** {zone['zone']}
💰 **Niveau :** ${niveau:.2f}
🎯 **Prix :** ${prix:.2f}

📝 **Analyse SMC en cours...**

---
⏳ Attends la confirmation pour un éventuel SETUP A+.
"""
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=msg,
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"❌ Erreur envoi: {e}")

# ============================================================
# MAIN
# ============================================================

async def main():
    verifier_instance_unique()
    
    # Initialiser le WebSocket
    ws = BybitWebSocket()
    await ws.connect()
    
    # Créer le bot
    bot = TradingBot(TELEGRAM_TOKEN, CHAT_ID, ws)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("help", bot.help))
    app.add_handler(CommandHandler("status", bot.status))
    app.add_handler(CommandHandler("scan", bot.scan))
    app.add_handler(CommandHandler("ping", bot.ping))
    app.add_handler(CommandHandler("price", bot.price))
    
    print("\n" + "="*60)
    print("🚀 Bot SMC Trading (WebSocket) démarré")
    print(f"📊 Symboles : {', '.join(SYMBOLS)}")
    print("🌐 Connexion WebSocket Bybit en cours...")
    print("="*60 + "\n")
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    while True:
        try:
            await bot.scanner()
        except Exception as e:
            print(f"❌ Erreur scan: {e}")
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Arrêt")
    finally:
    # ============================================================
# SERVEUR HTTP FACTICE POUR RENDER (ULTIME)
# ============================================================

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import socket

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot SMC Trading is running!")

def demarrer_serveur_factice():
    """Démarre un serveur HTTP sur le port 10000 avec gestion d'erreurs"""
    try:
        # Vérifier que le port est disponible
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0", 10000))
            print("✅ Port 10000 disponible")
        
        server = HTTPServer(("0.0.0.0", 10000), HealthHandler)
        print("✅ Serveur HTTP factice demarre sur le port 10000")
        server.serve_forever()
    except Exception as e:
        print(f"⚠️ Erreur serveur factice: {e}")

# Démarrer le serveur factice IMMÉDIATEMENT dans un thread séparé
thread = threading.Thread(target=demarrer_serveur_factice, daemon=True)
thread.start()
print("🚀 Thread du serveur factice lance")    nettoyer_pid()
# 
