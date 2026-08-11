import os
import asyncio
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from telegram import Bot
from telegram.ext import Application, CommandHandler

# ============================================================
# CONFIGURATION - À MODIFIER
# ============================================================

TELEGRAM_TOKEN = "8832221703:AAE5MwtZa9Y2UEakDWrtAtwaE8XyfPanGHI"
CHAT_ID = 6199209467

# Symboles à scanner
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]

# Intervalle de scan en secondes (60 = 1 minute)
SCAN_INTERVAL = 60

# ============================================================
# API BYBIT (PUBLIQUE - SANS CLÉ)
# ============================================================

class BybitAPI:
    def __init__(self):
        self.base_url = "https://api.bybit.com/v5"
    
    def get_price(self, symbol="BTCUSDT"):
        """Récupère le prix actuel et les 24h High/Low"""
        url = f"{self.base_url}/market/tickers"
        params = {"category": "linear", "symbol": symbol}
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if data["retCode"] != 0:
                print(f"❌ Erreur Bybit: {data['retMsg']}")
                return None
            t = data["result"]["list"][0]
            return {
                "symbol": symbol,
                "price": float(t["lastPrice"]),
                "high_24h": float(t["highPrice24h"]),
                "low_24h": float(t["lowPrice24h"])
            }
        except Exception as e:
            print(f"❌ Erreur get_price: {e}")
            return None
    
    def get_klines(self, symbol="BTCUSDT", interval="15", limit=50):
        """Récupère les bougies OHLCV"""
        url = f"{self.base_url}/market/kline"
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if data["retCode"] != 0:
                print(f"❌ Erreur klines: {data['retMsg']}")
                return None
            candles = data["result"]["list"]
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
            df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
            return df
        except Exception as e:
            print(f"❌ Erreur get_klines: {e}")
            return None

# ============================================================
# ANALYSE SMC
# ============================================================

class AnalyseSMC:
    def __init__(self):
        self.api = BybitAPI()
    
    def analyser(self, symbol, zone_touchee):
        """Analyse SMC complète après contact liquidité"""
        
        # Récupérer les données M15
        df = self.api.get_klines(symbol, "15", limit=50)
        if df is None or len(df) < 10:
            return {
                "verdict": "OBSERVATION_EN_COURS",
                "justification": "Données insuffisantes (M15)",
                "prix": 0
            }
        
        prix = df["close"].iloc[-1]
        
        # --- 3.1 SWEEP ---
        sweep = self.detecter_sweep(df, zone_touchee)
        
        # --- 3.2 CASSURE ---
        cassure = self.detecter_cassure(df, zone_touchee)
        
        # --- 3.3 REJET ---
        rejet = self.detecter_rejet(df, zone_touchee)
        
        # --- 3.4 CONSOLIDATION ---
        consolidation = self.detecter_consolidation(df)
        
        # --- 3.6 ACCEPTATION ---
        acceptation = self.detecter_acceptation(df, zone_touchee)
        
        # --- 3.7 REJET PRIX ---
        rejet_prix = self.detecter_rejet_prix(df, zone_touchee)
        
        # --- 4 DOMINANCE ---
        dominance = self.determiner_dominance(df)
        
        # --- 5 MSS ---
        mss = self.detecter_mss(df)
        
        # --- 6 DISPLACEMENT ---
        displacement = self.detecter_displacement(df)
        
        # --- 7 PULLBACK ---
        pullback = self.detecter_pullback(df)
        
        # --- MACD ---
        macd = self.calculer_macd(df)
        
        # --- SAR ---
        sar = self.calculer_sar(df)
        
        # --- ÉVALUATION ---
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
        """3.1 - Détection du SWEEP"""
        if len(df) < 2:
            return {"type": None, "confirme": False}
        
        d = df.iloc[-1]
        a = df.iloc[-2]
        niveau = zone["niveau"]
        
        if zone["zone"] == "24h_high":
            # SELL Sweep : high dépassé puis réintégré en dessous
            if a["high"] >= niveau and d["close"] < niveau:
                return {"type": "SELL", "confirme": True}
            return {"type": "SELL", "confirme": False}
        elif zone["zone"] == "24h_low":
            # BUY Sweep : low dépassé puis réintégré au-dessus
            if a["low"] <= niveau and d["close"] > niveau:
                return {"type": "BUY", "confirme": True}
            return {"type": "BUY", "confirme": False}
        return {"type": None, "confirme": False}
    
    def detecter_cassure(self, df, zone):
        """3.2 - Détection d'une cassure"""
        if len(df) < 3:
            return {"confirme": False, "direction": None}
        
        niveau = zone["niveau"]
        closes = df["close"].tail(3).tolist()
        
        if zone["zone"] == "24h_high":
            if closes[0] > niveau and closes[1] > niveau:
                return {"confirme": True, "direction": "HAUSSIERE"}
            return {"confirme": False, "direction": None}
        elif zone["zone"] == "24h_low":
            if closes[0] < niveau and closes[1] < niveau:
                return {"confirme": True, "direction": "BAISSIERE"}
            return {"confirme": False, "direction": None}
        return {"confirme": False, "direction": None}
    
    def detecter_rejet(self, df, zone):
        """3.3 - Détection d'un rejet"""
        if len(df) < 3:
            return {"confirme": False, "type": None}
        
        niveau = zone["niveau"]
        closes = df["close"].tail(3).tolist()
        highs = df["high"].tail(3).tolist()
        lows = df["low"].tail(3).tolist()
        
        if zone["zone"] == "24h_high":
            if highs[0] >= niveau and closes[0] < niveau and closes[1] < niveau:
                return {"confirme": True, "type": "BAISSIER"}
            return {"confirme": False, "type": None}
        elif zone["zone"] == "24h_low":
            if lows[0] <= niveau and closes[0] > niveau and closes[1] > niveau:
                return {"confirme": True, "type": "HAUSSIER"}
            return {"confirme": False, "type": None}
        return {"confirme": False, "type": None}
    
    def detecter_consolidation(self, df):
        """3.4 - Détection d'une consolidation"""
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
        """3.6 - Détection de l'acceptation du prix"""
        if len(df) < 2:
            return {"confirme": False, "type": None}
        
        niveau = zone["niveau"]
        dernier = df["close"].iloc[-1]
        avant = df["close"].iloc[-2]
        
        if zone["zone"] == "24h_high":
            if dernier > niveau and avant > niveau:
                return {"confirme": True, "type": "HAUSSIERE"}
            return {"confirme": False, "type": None}
        elif zone["zone"] == "24h_low":
            if dernier < niveau and avant < niveau:
                return {"confirme": True, "type": "BAISSIERE"}
            return {"confirme": False, "type": None}
        return {"confirme": False, "type": None}
    
    def detecter_rejet_prix(self, df, zone):
        """3.7 - Détection d'un rejet du prix"""
        if len(df) < 5:
            return {"confirme": False, "type": None}
        
        niveau = zone["niveau"]
        highs = df["high"].tail(5).tolist()
        lows = df["low"].tail(5).tolist()
        close = df["close"].iloc[-1]
        
        if zone["zone"] == "24h_high":
            if max(highs) >= niveau and close < niveau:
                return {"confirme": True, "type": "BAISSIER"}
            return {"confirme": False, "type": None}
        elif zone["zone"] == "24h_low":
            if min(lows) <= niveau and close > niveau:
                return {"confirme": True, "type": "HAUSSIER"}
            return {"confirme": False, "type": None}
        return {"confirme": False, "type": None}
    
    def determiner_dominance(self, df):
        """4 - Détermination de la dominance"""
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
        """5 - Détection des MSS (Micro, Intermédiaire, Majeur)"""
        if len(df) < 10:
            return {"mss_requis": False}
        
        closes = df["close"].tail(10).tolist()
        highs = df["high"].tail(10).tolist()
        lows = df["low"].tail(10).tolist()
        prix = closes[-1]
        
        # --- MSS Micro ---
        dh = max(highs[-3:])
        dl = min(lows[-3:])
        micro = {
            "confirme": prix > dh or prix < dl,
            "type": "BUY" if prix > dh else "SELL" if prix < dl else None
        }
        
        # --- MSS Intermédiaire (1H) ---
        df_1h = self.api.get_klines("BTCUSDT", "60", limit=10)
        if df_1h is not None and len(df_1h) >= 5:
            ih = max(df_1h["high"].tail(5).tolist())
            il = min(df_1h["low"].tail(5).tolist())
            inter = {
                "confirme": prix > ih or prix < il,
                "type": "BUY" if prix > ih else "SELL" if prix < il else None
            }
        else:
            inter = {"confirme": False, "type": None}
        
        # --- MSS Majeur (24h) ---
        ticker = self.api.get_price("BTCUSDT")
        if ticker:
            mh = ticker["high_24h"]
            ml = ticker["low_24h"]
            majeur = {
                "confirme": prix > mh or prix < ml,
                "type": "BUY" if prix > mh else "SELL" if prix < ml else None
            }
        else:
            majeur = {"confirme": False, "type": None}
        
        return {
            "micro": micro,
            "intermediaire": inter,
            "majeur": majeur,
            "mss_requis": inter["confirme"] or majeur["confirme"]
        }
    
    def detecter_displacement(self, df):
        """6 - Détection du Displacement"""
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
        """7 - Détection du Pullback"""
        if len(df) < 14:
            return {"confirme": False, "type": None}
        
        closes = df["close"].tolist()
        prix = closes[-1]
        
        ema7 = pd.Series(closes).ewm(span=7, adjust=False).mean().iloc[-1]
        ema14 = pd.Series(closes).ewm(span=14, adjust=False).mean().iloc[-1]
        
        # Voie A : Pullback classique sur EMA7
        if abs(prix - ema7) / ema7 < 0.001:
            return {"confirme": True, "type": "Voie A (classique)"}
        
        # Voie B : Pullback assoupli sur EMA14
        if abs(prix - ema14) / ema14 < 0.002 and prix > closes[-2]:
            return {"confirme": True, "type": "Voie B (assoupli)"}
        
        # Stabilisation
        if len(closes) >= 5:
            dernieres5 = closes[-5:]
            variation = (max(dernieres5) - min(dernieres5)) / min(dernieres5)
            if variation < 0.002:
                macd = self.calculer_macd(df)
                if macd["histogram"] > 0:
                    return {"confirme": True, "type": "Voie B (stabilisation)"}
        
        return {"confirme": False, "type": None}
    
    def calculer_macd(self, df):
        """Calcule le MACD"""
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
        """Calcule le SAR approximatif"""
        if len(df) < 5:
            return {"prix_vs_sar": "INCONNU"}
        
        highs = df["high"].tail(5).tolist()
        lows = df["low"].tail(5).tolist()
        close = df["close"].iloc[-1]
        
        if close > df["close"].iloc[-2]:
            sar = min(lows) * 0.98
            return {
                "valeur": round(sar, 2),
                "type": "HAUSSIER",
                "prix_vs_sar": "AU_DESSUS" if close > sar else "EN_DESSOUS"
            }
        else:
            sar = max(highs) * 1.02
            return {
                "valeur": round(sar, 2),
                "type": "BAISSIER",
                "prix_vs_sar": "AU_DESSUS" if close > sar else "EN_DESSOUS"
            }
    
    def evaluer_setup(self, sweep, mss, displacement, pullback):
        """Évalue si toutes les conditions pour un SETUP A+ sont réunies"""
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
        self.api = BybitAPI()
        self.analyse = AnalyseSMC()
        self.dernieres_zones = {}
        self.derniers_prix = {}
    
    async def start(self, update, context):
        await update.message.reply_text(
            "🤖 **Bot SMC Trading**\n\n"
            "Je scanne automatiquement BTC, ETH, SOL et XRP.\n"
            "Dès qu'une liquidité est touchée, j'analyse en M15.\n\n"
            "📊 **Commandes :**\n"
            "/start - Démarrer\n"
            "/scan - Scan manuel\n"
            "/status - État du bot\n"
            "/help - Aide",
            parse_mode="Markdown"
        )
    
    async def help(self, update, context):
        await update.message.reply_text(
            "🤖 **Aide**\n\n"
            "• Scan permanent des liquidités (24h High/Low)\n"
            "• Analyse SMC (Sweep, MSS, Displacement, Pullback)\n"
            "• Alerte si SETUP A+ détecté\n\n"
            "Symboles : BTC, ETH, SOL, XRP",
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
        """Commande /scan - Scan manuel"""
        await update.message.reply_text("🔍 Scan manuel en cours...")
        await self.scanner()
    
    async def scanner(self):
        """Scan automatique de tous les symboles"""
        print(f"\n🔍 [{datetime.now().strftime('%H:%M:%S')}] Scan en cours...")
        
        for symbol in SYMBOLS:
            # Récupérer les données
            data = self.api.get_price(symbol)
            if not data:
                print(f"❌ {symbol}: Impossible de récupérer les données")
                continue
            
            prix = data["price"]
            high = data["high_24h"]
            low = data["low_24h"]
            
            print(f"   📊 {symbol}: prix={prix}, high={high}, low={low}")
            
            # Initialiser si premier scan
            if symbol not in self.dernieres_zones:
                self.dernieres_zones[symbol] = None
                self.derniers_prix[symbol] = prix
            
            zone_touchee = None
            
            # Détection 24h HIGH
            if prix >= high:
                if self.dernieres_zones[symbol] != "24h_high":
                    zone_touchee = {"zone": "24h_high", "niveau": high}
                    self.dernieres_zones[symbol] = "24h_high"
                    print(f"🔔 {symbol} - 24h HIGH touchée ! (prix: {prix})")
            
            # Détection 24h LOW
            elif prix <= low:
                if self.dernieres_zones[symbol] != "24h_low":
                    zone_touchee = {"zone": "24h_low", "niveau": low}
                    self.dernieres_zones[symbol] = "24h_low"
                    print(f"🔔 {symbol} - 24h LOW touchée ! (prix: {prix})")
            
            # Si une zone est touchée, on analyse
            if zone_touchee:
                print(f"📊 Analyse SMC en cours pour {symbol}...")
                analyse = self.analyse.analyser(symbol, zone_touchee)
                analyse["prix"] = prix  # S'assurer que le prix est bien passé
                
                # Envoyer l'alerte
                await self.envoyer_alerte(symbol, zone_touchee, analyse)
            
            # Mettre à jour le dernier prix
            self.derniers_prix[symbol] = prix
        
        print(f"✅ Scan terminé à {datetime.now().strftime('%H:%M:%S')}")
    
    async def envoyer_alerte(self, symbol, zone, analyse):
        """Envoie l'alerte sur Telegram"""
        verdict = analyse.get("verdict", {})
        prix = analyse.get("prix", 0)
        niveau = zone["niveau"]
        
        # Message d'observation (par défaut)
        if verdict.get("verdict") != "SETUP_A+":
            msg = f"""
ℹ️ **OBSERVATION EN COURS**

📊 **Actif :** {symbol}
📍 **Zone :** {zone['zone']}
💰 **Niveau :** ${niveau:.2f}
🎯 **Prix :** ${prix:.2f}

📊 **Analyse :**
• Sweep : {'✅' if analyse.get('sweep', {}).get('confirme') else '❌'}
• MSS : {'✅' if analyse.get('mss', {}).get('mss_requis') else '❌'}
• Displacement : {'✅' if analyse.get('displacement', {}).get('confirme') else '❌'}
• Pullback : {'✅' if analyse.get('pullback', {}).get('confirme') else '❌'}

📊 **Indicateurs :**
• MACD : {analyse.get('macd', {}).get('croisement', 'INCONNU')}
• Dominance : {analyse.get('dominance', {}).get('dominant', 'Neutre')}

📝 **{verdict.get('justification', 'En attente de confirmation')}**

---
⏳ Le bot continue de surveiller.
"""
        else:
            # SETUP A+
            direction = verdict["direction"]
            
            if direction == "BUY":
                sl = round(niveau * 0.99, 2)
                tp1 = round(prix + (prix - sl) * 2, 2)
                tp2 = round(prix + (prix - sl) * 3, 2)
            else:
                sl = round(niveau * 1.01, 2)
                tp1 = round(prix - (sl - prix) * 2, 2)
                tp2 = round(prix - (sl - prix) * 3, 2)
            
            rr = round(abs((tp1 - prix) / (prix - sl)) if (prix - sl) != 0 else 0, 2)
            
            msg = f"""
🔔 **SETUP A+ DÉTECTÉ !**

📊 **Actif :** {symbol}
📍 **Zone :** {zone['zone']}
💰 **Niveau :** ${niveau:.2f}
🎯 **Prix :** ${prix:.2f}

📈 **Direction :** **{direction}**
🛑 **Stop Loss :** ${sl:.2f}
🎯 **TP1 :** ${tp1:.2f}
🎯 **TP2 :** ${tp2:.2f}
📐 **Risk/Reward :** {rr}

📊 **Analyse :**
• Sweep : ✅ {direction}
• MSS : ✅ Confirmé
• Displacement : ✅ Confirmé
• Pullback : ✅ Confirmé
• MACD : {analyse.get('macd', {}).get('croisement', 'INCONNU')}
• Dominance : {analyse.get('dominance', {}).get('dominant', 'Neutre')}

📝 **{verdict.get('justification', '')}**

---
⚠️ Alerte automatique. Fais tes propres vérifications.
"""
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=msg,
                parse_mode="Markdown"
            )
            print(f"✅ Alerte envoyée pour {symbol}")
        except Exception as e:
            print(f"❌ Erreur envoi Telegram: {e}")

# ============================================================
# MAIN
# ============================================================

async def main():
    bot = TradingBot(TELEGRAM_TOKEN, CHAT_ID)
    
    # Créer l'application Telegram
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Ajouter les commandes
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("help", bot.help))
    app.add_handler(CommandHandler("status", bot.status))
    app.add_handler(CommandHandler("scan", bot.scan))
    
    print("🚀 Bot SMC Trading démarré !")
    print(f"📊 Symboles : {', '.join(SYMBOLS)}")
    print(f"⏳ Intervalle : {SCAN_INTERVAL}s")
    print("🤖 En attente des commandes...")
    
    # Démarrer le polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # Boucle de scan automatique
    while True:
        try:
            await bot.scanner()
        except Exception as e:
            print(f"❌ Erreur dans la boucle de scan: {e}")
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
