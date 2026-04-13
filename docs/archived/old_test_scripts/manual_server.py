import sys
from tdmclient.server import Server
from tdmclient.tcp import TDMServerTCP
from tdmclient.nodes_local import NodesLocal

def run_server():
    print("Tentative de démarrage manuel du serveur TDM...")
    try:
        # 1. 强制初始化本地节点发现（直接扫串口）
        nodes_local = NodesLocal()
        
        # 2. 创建 TDM 核心服务逻辑
        server = Server(nodes_local=nodes_local)
        
        # 3. 绑定 TCP 端口 8596
        # 这是为了骗过你的 thymio_bridge.py
        tcp_server = TDMServerTCP(server, 8596)
        
        print("Serveur prêt, écoute sur le port : 8596")
        print("Recherche de robots en cours, veuillez vérifier que usbipd est attaché et que chmod a été exécuté...")
        
        # 4. 进入永久循环
        tcp_server.run()
    except Exception as e:
        print(f"Échec du démarrage : {e}")

if __name__ == "__main__":
    run_server()
