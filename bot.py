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

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
SCAN_INTERVAL = 60  # Secondes entre chaque scan

# ============================================================
# API BYBIT (PUBLIQUE - SANS CLÉ)
# ============================================================

class BybitAPI:
    def __init__(self):
        self.base_url = "https://api.bybit.com/v5"
    
    def get_price(self, symbol="BTCUSDT"):
        url = f"{self.base_url}/market/tickers"
        params = {"category": "linear", "symbol": symbol}
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if data["retCode"] != 0:
                return None
            t = data["result"]["list"][0]
            return {
                "symbol": symbol,
                "price": float(t["lastPrice"]),
                "high_24h": float(t["highPrice24h"]),
                "low_24h": float(t["lowPrice24h"])
            }
        except:
            return None
    
    def get_klines(self, symbol="BTCUSDT", interval="15", limit=50):
        url = f"{self.base_url}/market/kline"
        params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit}
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if data["retCode"] != 0:
                return None
            candles = data["result"]["list"]
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
            df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
            return df
        except:
            return None

# ============================================================
# ANALYSE SMC
# ============================================================

class AnalyseSMC:
    def __init__(self):
        self.api = BybitAPI()
    
    def analyser(self, symbol, zone_touchee):
        df = self.api.get_klines(symbol, "15", limit=50)
        if df is None or len(df) < 10:
            return {"verdict": "OBSERVATION_EN_COURS", "justification": "Données insuffisantes"}
        
        prix = df["close"].iloc[-1]
        
        # --- SWEEP ---
        sweep = self.detecter_sweep(df, zone_touchee)
        
        # --- MSS ---
        mss = self.detecter_mss(df)
        
        # --- DISPLACEMENT ---
        displacement = self.detecter_displacement(df)
        
        # --- PULLBACK ---
        pullback = self.detecter_pullback(df)
        
        # --- MACD ---
        macd = self.calculer_macd(df)
        
        # --- DOMINANCE ---
        dominance = self.determiner_dominance(df)
        
        # --- SAR ---
        sar = self.calculer_sar(df)
        
        # --- ÉVALUATION ---
        verdict = self.evaluer_setup(sweep, mss, displacement, pullback)
        
        return {
            "symbol": symbol,
            "prix": round(prix, 2),
            "zone": zone_touchee,
            "sweep": sweep,
            "mss": mss,
            "displacement": displacement,
            "pullback": pullback,
            "macd": macd,
            "dominance": dominance,
            "sar": sar,
            "verdict": verdict
        }
    
    def detecter_sweep(self, df, zone):
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
    
    def detecter_mss(self, df):
        closes = df["close"].tail(10).tolist()
        highs = df["high"].tail(10).tolist()
        lows = df["low"].tail(10).tolist()
        prix = closes[-1]
        
        # Micro
        dh = max(highs[-3:])
        dl = min(lows[-3:])
        micro = {"confirme": prix > dh or prix < dl, "type": "BUY" if prix > dh else "SELL"}
        
        # Intermédiaire (sur 5 bougies 1H)
        df_1h = self.api.get_klines("BTCUSDT", "60", limit=10)
        if df_1h is not None and len(df_1h) >= 5:
            ih = max(df_1h["high"].tail(5).tolist())
            il = min(df_1h["low"].tail(5).tolist())
            inter = {"confirme": prix > ih or prix < il, "type": "BUY" if prix > ih else "SELL"}
        else:
            inter = {"confirme": False, "type": None}
        
        # Majeur (24h)
        ticker = self.api.get_price("BTCUSDT")
        if ticker:
            mh = ticker["high_24h"]
            ml = ticker["low_24h"]
            majeur = {"confirme": prix > mh or prix < ml, "type": "BUY" if prix > mh else "SELL"}
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
            return {"confirme": False}
        d = df.iloc[-1]
        p = df.iloc[-6:-1]
        taille = abs(d["close"] - d["open"])
        moy = sum(abs(p.iloc[i]["close"] - p.iloc[i]["open"]) for i in range(len(p))) / len(p) if len(p) > 0 else 0
        if moy == 0:
            return {"confirme": False}
        rang = d["high"] - d["low"]
        if rang > 0:
            pos = (d["close"] - d["low"]) / rang
        else:
            pos = 0.5
        type_disp = "BUY" if pos > 0.75 else "SELL" if pos < 0.25 else None
        return {"confirme": taille > moy * 1.2 and type_disp is not None, "type": type_disp}
    
    def detecter_pullback(self, df):
        if len(df) < 14:
            return {"confirme": False}
        closes = df["close"].tolist()
        ema7 = pd.Series(closes).ewm(span=7, adjust=False).mean().iloc[-1]
        ema14 = pd.Series(closes).ewm(span=14, adjust=False).mean().iloc[-1]
        prix = closes[-1]
        
        if abs(prix - ema7) / ema7 < 0.001:
            return {"confirme": True, "type": "Voie A"}
        elif abs(prix - ema14) / ema14 < 0.002 and prix > closes[-2]:
            return {"confirme": True, "type": "Voie B"}
        return {"confirme": False}
    
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
    
    def determiner_dominance(self, df):
        closes = df["close"].tolist()
        prix = closes[-1]
        ma7 = sum(closes[-7:]) / 7 if len(closes) >= 7 else prix
        ma14 = sum(closes[-14:]) / 14 if len(closes) >= 14 else prix
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
                "justification": f"Sweep {sweep['type']} ✅, MSS ✅, Displacement ✅, Pullback ✅"
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
        await update.message.reply_text("🔍 Scan manuel en cours...")
        await self.scanner()
    
    async def scanner(self):
        for symbol in SYMBOLS:
            # Détection
            data = self.api.get_price(symbol)
            if not data:
                continue
            
            prix = data["price"]
            high = data["high_24h"]
            low = data["low_24h"]
            
            if symbol not in self.dernieres_zones:
                self.dernieres_zones[symbol] = None
            
            zone_touchee = None
            if prix >= high and self.dernieres_zones[symbol] != "24h_high":
                zone_touchee = {"zone": "24h_high", "niveau": high}
                self.dernieres_zones[symbol] = "24h_high"
            elif prix <= low and self.dernieres_zones[symbol] != "24h_low":
                zone_touchee = {"zone": "24h_low", "niveau": low}
                self.dernieres_zones[symbol] = "24h_low"
            
            if zone_touchee:
                print(f"🔔 {symbol} - {zone_touchee['zone']} touchée !")
                analyse = self.analyse.analyser(symbol, zone_touchee)
                await self.envoyer_alerte(symbol, zone_touchee, analyse)
    
    async def envoyer_alerte(self, symbol, zone, analyse):
        verdict = analyse.get("verdict", {})
        
        if verdict.get("verdict") == "SETUP_A+":
            direction = verdict["direction"]
            prix = analyse["prix"]
            niveau = zone["niveau"]
            
            if direction == "BUY":
                sl = niveau * 0.99
                tp1 = prix + (prix - sl) * 2
                tp2 = prix + (prix - sl) * 3
            else:
                sl = niveau * 1.01
                tp1 = prix - (sl - prix) * 2
                tp2 = prix - (sl - prix) * 3
            
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
• MACD : {analyse['macd']['croisement']}
• Dominance : {analyse['dominance']['dominant']}

📝 **{verdict['justification']}**

---
⚠️ Alerte automatique. Fais tes propres vérifications.
"""
        else:
            msg = f"""
ℹ️ **OBSERVATION EN COURS**

📊 **Actif :** {symbol}
📍 **Zone :** {zone['zone']}
💰 **Niveau :** ${zone['niveau']:.2f}
🎯 **Prix :** ${analyse['prix']:.2f}

📊 **{verdict.get('justification', 'En attente de confirmation')}**

---
⏳ Le bot continue de surveiller.
"""
        
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Erreur envoi: {e}")

# ============================================================
# MAIN
# ============================================================

async def main():
    bot = TradingBot(TELEGRAM_TOKEN, CHAT_ID)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("help", bot.help))
    app.add_handler(CommandHandler("status", bot.status))
    app.add_handler(CommandHandler("scan", bot.scan))
    
    print("🚀 Bot SMC Trading démarré !")
    print(f"📊 Symboles : {', '.join(SYMBOLS)}")
    print(f"⏳ Intervalle : {SCAN_INTERVAL}s")
    print("🤖 En attente des commandes...")
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # Scan automatique
    while True:
        await bot.scanner()
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())