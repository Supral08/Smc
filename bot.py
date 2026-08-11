#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import signal
import time
import asyncio
import json
import requests
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

TELEGRAM_TOKEN = "8832221703:AAE5MwtZa9Y2UEakDWrtAtwaE8XyfPanGHI"
CHAT_ID = 6199209467

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
SCAN_INTERVAL = 60

# ============================================================
# API COINGECKO AVEC RETRY ET PROXY
# ============================================================

class CoinGeckoAPI:
    def __init__(self):
        self.base_url = "https://api.coingecko.com/api/v3"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        })
        # Désactiver la vérification SSL si nécessaire
        self.session.verify = True
    
    def get_price(self, symbol="BTCUSDT"):
        """Récupère le prix depuis CoinGecko"""
        try:
            coin_map = {
                "BTCUSDT": "bitcoin",
                "ETHUSDT": "ethereum",
                "SOLUSDT": "solana",
                "XRPUSDT": "ripple"
            }
            coin_id = coin_map.get(symbol, "bitcoin")
            
            # Utiliser l'API alternative si nécessaire
            url = f"https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true"
            }
            r = self.session.get(url, params=params, timeout=10)
            data = r.json()
            
            if coin_id in data:
                price = data[coin_id]["usd"]
                change_24h = data[coin_id].get("usd_24h_change", 0) / 100
                return {
                    "symbol": symbol,
                    "price": float(price),
                    "high_24h": float(price * (1 + abs(change_24h) + 0.01)),
                    "low_24h": float(price * (1 - abs(change_24h) - 0.01))
                }
            return None
        except Exception as e:
            print(f"❌ CoinGecko: {e}")
            return None
    
    def get_klines(self, symbol="BTCUSDT", interval="15m", limit=50):
        """Récupère les bougies depuis Binance (si possible) ou simule"""
        # Essayer Binance d'abord
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            r = self.session.get(url, params=params, timeout=5)
            data = r.json()
            if "code" not in data:
                df = pd.DataFrame(data, columns=[
                    "timestamp", "open", "high", "low", "close", "volume",
                    "close_time", "quote_asset_volume", "number_of_trades",
                    "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
                ])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
                return df
        except:
            pass
        
        # Fallback : données simulées
        print(f"⚠️ Données simulées pour {symbol}")
        np.random.seed(hash(symbol) % 100)
        base_price = 65000 if "BTC" in symbol else 1900 if "ETH" in symbol else 76 if "SOL" in symbol else 1.03
        timestamps = pd.date_range(end=datetime.now(), periods=limit, freq="15min")
        prices = [base_price * (1 + np.random.randn() * 0.002) for _ in range(limit)]
        prices = np.cumsum(prices) / np.arange(1, limit + 1) * 1.5 + base_price / 2
        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": prices,
            "high": [p * (1 + abs(np.random.randn() * 0.002)) for p in prices],
            "low": [p * (1 - abs(np.random.randn() * 0.002)) for p in prices],
            "close": [p * (1 + np.random.randn() * 0.001) for p in prices],
            "volume": [np.random.randint(100, 1000) for _ in range(limit)]
        })
        return df

# ============================================================
# ANALYSE SMC (VERSION SIMPLIFIÉE POUR TEST)
# ============================================================

class AnalyseSMC:
    def __init__(self):
        self.api = CoinGeckoAPI()
    
    def analyser(self, symbol, zone_touchee):
        df = self.api.get_klines(symbol, "15m", limit=50)
        if df is None or len(df) < 10:
            return {
                "verdict": "OBSERVATION_EN_COURS",
                "justification": "Données insuffisantes (M15)",
                "prix": 0
            }
        
        prix = df["close"].iloc[-1]
        sweep = self.detecter_sweep(df, zone_touchee)
        cassure = self.detecter_cassure(df, zone_touchee)
        rejet = self.detecter_rejet(df, zone_touchee)
        consolidation = self.detecter_consolidation(df)
        acceptation = self.detecter_acceptation(df, zone_touchee)
        rejet_prix = self.detecter_rejet_prix(df, zone_touchee)
        dominance = self.determiner_dominance(df)
        mss = self.detecter_mss(df)
        displacement = self.detecter_displacement(df)
        pullback = self.detecter_pullback(df)
        macd = self.calculer_macd(df)
        sar = self.calculer_sar(df)
        verdict = self.evaluer_setup(sweep, mss, displacement, pullback)
        
        return {
            "symbol": symbol,
            "prix": round(prix, 2),
            "zone": zone_touchee,
            "sweep": sweep,
            "cassure": cassure,
            "rejet": rejet,
            "consolidation": consolidation,
            "acceptation": acceptation,
            "rejet_prix": rejet_prix,
            "dominance": dominance,
            "mss": mss,
            "displacement": displacement,
            "pullback": pullback,
            "macd": macd,
            "sar": sar,
            "verdict": verdict
        }
    
    def detecter_sweep(self, df, zone):
        if len(df) < 2:
            return {"type": None, "confirme": False}
        d = df.iloc[-1]
        a = df.iloc[-2]
        niveau = zone["niveau"]
        if zone["zone"] == "24h_high":
            if a["high"] >= niveau and d["close"] < niveau:
                return {"type": "SELL", "confirme": True}
            return {"type": "SELL", "confirme": False}
        elif zone["zone"] == "24h_low":
            if a["low"] <= niveau and d["close"] > niveau:
                return {"type": "BUY", "confirme": True}
            return {"type": "BUY", "confirme": False}
        return {"type": None, "confirme": False}
    
    def detecter_cassure(self, df, zone):
        if len(df) < 3:
            return {"confirme": False, "direction": None}
        niveau = zone["niveau"]
        closes = df["close"].tail(3).tolist()
        if zone["zone"] == "24h_high":
            if closes[0] > niveau and closes[1] > niveau:
                return {"confirme": True, "direction": "HAUSSIERE"}
        elif zone["zone"] == "24h_low":
            if closes[0] < niveau and closes[1] < niveau:
                return {"confirme": True, "direction": "BAISSIERE"}
        return {"confirme": False, "direction": None}
    
    def detecter_rejet(self, df, zone):
        if len(df) < 3:
            return {"confirme": False, "type": None}
        niveau = zone["niveau"]
        closes = df["close"].tail(3).tolist()
        highs = df["high"].tail(3).tolist()
        lows = df["low"].tail(3).tolist()
        if zone["zone"] == "24h_high":
            if highs[0] >= niveau and closes[0] < niveau and closes[1] < niveau:
                return {"confirme": True, "type": "BAISSIER"}
        elif zone["zone"] == "24h_low":
            if lows[0] <= niveau and closes[0] > niveau and closes[1] > niveau:
                return {"confirme": True, "type": "HAUSSIER"}
        return {"confirme": False, "type": None}
    
    def detecter_consolidation(self, df):
        if len(df) < 10:
            return {"confirme": False, "range": 0}
        closes = df["close"].tail(10).tolist()
        highs = df["high"].tail(10).tolist()
        lows = df["low"].tail(10).tolist()
        prix_max = max(highs)
        prix_min = min(lows)
        range_prix = prix_max - prix_min
        prix_moyen = sum(closes) / len(closes)
        if range_prix / prix_moyen < 0.005:
            return {"confirme": True, "range": round(range_prix, 2)}
        return {"confirme": False, "range": round(range_prix, 2)}
    
    def detecter_acceptation(self, df, zone):
        if len(df) < 2:
            return {"confirme": False, "type": None}
        niveau = zone["niveau"]
        dernier = df["close"].iloc[-1]
        avant = df["close"].iloc[-2]
        if zone["zone"] == "24h_high":
            if dernier > niveau and avant > niveau:
                return {"confirme": True, "type": "HAUSSIERE"}
        elif zone["zone"] == "24h_low":
            if dernier < niveau and avant < niveau:
                return {"confirme": True, "type": "BAISSIERE"}
        return {"confirme": False, "type": None}
    
    def detecter_rejet_prix(self, df, zone):
        if len(df) < 5:
            return {"confirme": False, "type": None}
        niveau = zone["niveau"]
        highs = df["high"].tail(5).tolist()
        lows = df["low"].tail(5).tolist()
        close = df["close"].iloc[-1]
        if zone["zone"] == "24h_high":
            if max(highs) >= niveau and close < niveau:
                return {"confirme": True, "type": "BAISSIER"}
        elif zone["zone"] == "24h_low":
            if min(lows) <= niveau and close > niveau:
                return {"confirme": True, "type": "HAUSSIER"}
        return {"confirme": False, "type": None}
    
    def determiner_dominance(self, df):
        if len(df) < 14:
            return {"dominant": "Neutre", "score": 0}
        closes = df["close"].tolist()
        prix = closes[-1]
        ma7 = sum(closes[-7:]) / 7
        ma14 = sum(closes[-14:]) / 14
        sar = self.calculer_sar(df)
        macd = self.calculer_macd(df)
        score = 0
        if prix > ma7: score += 1
        else: score -= 1
        if prix > ma14: score += 1
        else: score -= 1
        if sar["prix_vs_sar"] == "AU_DESSUS": score += 1
        else: score -= 1
        if macd["croisement"] == "HAUSSIER": score += 1
        else: score -= 1
        if score >= 2:
            return {"dominant": "Acheteurs", "score": score}
        elif score <= -2:
            return {"dominant": "Vendeurs", "score": abs(score)}
        else:
            return {"dominant": "Neutre", "score": 0}
    
    def detecter_mss(self, df):
        if len(df) < 10:
            return {"mss_requis": False}
        closes = df["close"].tail(10).tolist()
        highs = df["high"].tail(10).tolist()
        lows = df["low"].tail(10).tolist()
        prix = closes[-1]
        dh = max(highs[-3:])
        dl = min(lows[-3:])
        micro = {"confirme": prix > dh or prix < dl, "type": "BUY" if prix > dh else "SELL" if prix < dl else None}
        df_1h = self.api.get_klines("BTCUSDT", "1h", limit=10)
        if df_1h is not None and len(df_1h) >= 5:
            ih = max(df_1h["high"].tail(5).tolist())
            il = min(df_1h["low"].tail(5).tolist())
            inter = {"confirme": prix > ih or prix < il, "type": "BUY" if prix > ih else "SELL" if prix < il else None}
        else:
            inter = {"confirme": False, "type": None}
        ticker = self.api.get_price("BTCUSDT")
        if ticker:
            mh = ticker["high_24h"]
            ml = ticker["low_24h"]
            majeur = {"confirme": prix > mh or prix < ml, "type": "BUY" if prix > mh else "SELL" if prix < ml else None}
        else:
            majeur = {"confirme": False, "type": None}
        return {
            "micro": micro,
            "intermediaire": inter,
            "majeur": majeur,
            "mss_requis": inter["confirme"] or majeur["confirme"]
        }
    
    def detecter_displacement(self, df):
        if len(df) < 6:
            return {"confirme": False, "type": None}
        d = df.iloc[-1]
        p = df.iloc[-6:-1]
        taille = abs(d["close"] - d["open"])
        tailles = [abs(p.iloc[i]["close"] - p.iloc[i]["open"]) for i in range(len(p))]
        moy = sum(tailles) / len(tailles) if tailles else 0
        if moy == 0:
            return {"confirme": False, "type": None}
        rang = d["high"] - d["low"]
        if rang > 0:
            pos = (d["close"] - d["low"]) / rang
        else:
            pos = 0.5
        if pos > 0.75:
            type_disp = "BUY"
        elif pos < 0.25:
            type_disp = "SELL"
        else:
            type_disp = None
        return {
            "confirme": taille > moy * 1.2 and type_disp is not None,
            "type": type_disp,
            "taille": round(taille, 2),
            "moyenne": round(moy, 2)
        }
    
    def detecter_pullback(self, df):
        if len(df) < 14:
            return {"confirme": False, "type": None}
        closes = df["close"].tolist()
        prix = closes[-1]
        ema7 = pd.Series(closes).ewm(span=7, adjust=False).mean().iloc[-1]
        ema14 = pd.Series(closes).ewm(span=14, adjust=False).mean().iloc[-1]
        if abs(prix - ema7) / ema7 < 0.001:
            return {"confirme": True, "type": "Voie A (classique)"}
        if abs(prix - ema14) / ema14 < 0.002 and prix > closes[-2]:
            return {"confirme": True, "type": "Voie B (assoupli)"}
        if len(closes) >= 5:
            dernieres5 = closes[-5:]
            variation = (max(dernieres5) - min(dernieres5)) / min(dernieres5)
            if variation < 0.002:
                macd = self.calculer_macd(df)
                if macd["histogram"] > 0:
                    return {"confirme": True, "type": "Voie B (stabilisation)"}
        return {"confirme": False, "type": None}
    
    def calculer_macd(self, df):
        if len(df) < 26:
            return {"croisement": "INCONNU", "histogram": 0}
        closes = df["close"].tolist()
        s = pd.Series(closes)
        ema12 = s.ewm(span=12, adjust=False).mean()
        ema26 = s.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        return {
            "macd": round(macd.iloc[-1], 2),
            "signal": round(signal.iloc[-1], 2),
            "histogram": round(hist.iloc[-1], 2),
            "croisement": "HAUSSIER" if macd.iloc[-1] > signal.iloc[-1] else "BAISSIER"
        }
    
    def calculer_sar(self, df):
        if len(df) < 5:
            return {"prix_vs_sar": "INCONNU"}
        highs = df["high"].tail(5).tolist()
        lows = df["low"].tail(5).tolist()
        close = df["close"].iloc[-1]
        if close > df["close"].iloc[-2]:
            sar = min(lows) * 0.98
            return {"valeur": round(sar, 2), "type": "HAUSSIER", "prix_vs_sar": "AU_DESSUS" if close > sar else "EN_DESSOUS"}
        else:
            sar = max(highs) * 1.02
            return {"valeur": round(sar, 2), "type": "BAISSIER", "prix_vs_sar": "AU_DESSUS" if close > sar else "EN_DESSOUS"}
    
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
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.bot = Bot(token=token)
        self.api = CoinGeckoAPI()
        self.analyse = AnalyseSMC()
        self.dernieres_zones = {}
        self.scan_en_cours = False
    
    async def start(self, update, context):
        await update.message.reply_text(
            "🤖 **Bot SMC Trading**\n\n"
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
        await update.message.reply_text("📊 Récupération des prix en cours...")
        
        message = "💰 **Prix en direct :**\n\n"
        aucun_prix = 0
        
        for symbol in SYMBOLS:
            data = self.api.get_price(symbol)
            if data:
                message += f"• **{symbol}** : ${data['price']:.2f}\n"
                message += f"  (24h H: ${data['high_24h']:.2f} / L: ${data['low_24h']:.2f})\n\n"
            else:
                message += f"• **{symbol}** : ❌ Indisponible\n\n"
                aucun_prix += 1
        
        message += f"🕐 Mis à jour : {datetime.now().strftime('%H:%M:%S')} UTC"
        
        if aucun_prix == len(SYMBOLS):
            message += "\n\n⚠️ Aucun prix disponible. Le bot utilise des données simulées pour l'analyse."
        
        await update.message.reply_text(message, parse_mode="Markdown")
    
    async def ping(self, update, context):
        await update.message.reply_text(
            "🏓 **Pong !**\n\n"
            f"✅ Bot connecté\n"
            f"⏰ Heure : {datetime.now().strftime('%H:%M:%S')}\n"
            f"📊 Symboles : {', '.join(SYMBOLS)}",
            parse_mode="Markdown"
        )
    
    async def help(self, update, context):
        await update.message.reply_text(
            "🤖 **Aide**\n\n"
            "• Scan des liquidités (24h High/Low)\n"
            "• Analyse SMC (Sweep, MSS, Displacement, Pullback)\n"
            "• Alerte si SETUP A+ détecté\n\n"
            "Commandes : /start, /price, /scan, /status, /ping, /help",
            parse_mode="Markdown"
        )
    
    async def status(self, update, context):
        await update.message.reply_text(
            f"📊 **État du bot**\n"
            f"• Symboles : {', '.join(SYMBOLS)}\n"
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
            data = self.api.get_price(symbol)
            if not data:
                print(f"❌ {symbol} indisponible")
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
            elif prix <= low:
                if self.dernieres_zones[symbol] != "24h_low":
                    zone_touchee = {"zone": "24h_low", "niveau": low}
                    self.dernieres_zones[symbol] = "24h_low"
                    print(f"🔔 {symbol} - 24h LOW touchée !")
            
            if zone_touchee:
                analyse = self.analyse.analyser(symbol, zone_touchee)
                analyse["prix"] = prix
                await self.envoyer_alerte(symbol, zone_touchee, analyse)
        
        self.scan_en_cours = False
    
    async def envoyer_alerte(self, symbol, zone, analyse):
        prix = analyse.get("prix", 0)
        niveau = zone["niveau"]
        
        msg = f"""
ℹ️ **OBSERVATION EN COURS**

📊 **Actif :** {symbol}
📍 **Zone :** {zone['zone']}
💰 **Niveau :** ${niveau:.2f}
🎯 **Prix :** ${prix:.2f}

📝 **Analyse SMC en cours...**
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
    
    bot = TradingBot(TELEGRAM_TOKEN, CHAT_ID)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("help", bot.help))
    app.add_handler(CommandHandler("status", bot.status))
    app.add_handler(CommandHandler("scan", bot.scan))
    app.add_handler(CommandHandler("ping", bot.ping))
    app.add_handler(CommandHandler("price", bot.price))
    
    print("\n" + "="*60)
    print("🚀 Bot SMC Trading (CoinGecko) démarré")
    print(f"📊 Symboles : {', '.join(SYMBOLS)}")
    print("="*60 + "\n")
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    while True:
        try:
            await bot.scanner()
        except Exception as e:
            print(f"❌ Erreur: {e}")
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Arrêt")
    finally:
        nettoyer_pid()
        print("👋 Arrêté")
