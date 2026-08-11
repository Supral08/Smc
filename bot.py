# ============================================================
# SERVEUR HTTP FACTICE POUR RENDER
# ============================================================

import threading
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler

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
    
    # Démarrer le serveur factice dans un thread séparé
    thread = threading.Thread(target=demarrer_serveur_factice, daemon=True)
    thread.start()
    print("🚀 Thread du serveur factice lance")
    
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
        print("\n🛑 Arrêt demande par l'utilisateur")
    finally:
        nettoyer_pid()
        print("👋 Bot arrêté")
