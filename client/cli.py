import sys
from client.connection import GameClient

ASCII_HANGMAN = [
    """
       ------
       |    |
       |
       |
       |
       |
    ========
    """,
    """
       ------
       |    |
       |    O
       |
       |
       |
    ========
    """,
    """
       ------
       |    |
       |    O
       |    |
       |
       |
    ========
    """,
    """
       ------
       |    |
       |    O
       |   /|
       |
       |
    ========
    """,
    """
       ------
       |    |
       |    O
       |   /|\\
       |
       |
    ========
    """,
    """
       ------
       |    |
       |    O
       |   /|\\
       |   /
       |
    ========
    """,
    """
       ------
       |    |
       |    O
       |   /|\\
       |   / \\
       |
    ========
    """
]


def show_state(resp) -> None:
    p = resp.payload
    errors_left = p.get("errors_left", 6)
    stage = max(0, min(6, 6 - errors_left))
    print(ASCII_HANGMAN[stage])
    print(f"Mot            : {p.get('masked_word', '')}")
    print(f"Essais restants: {errors_left}")
    used = p.get("used_letters", [])
    print(f"Lettres jouées : {', '.join(used) if used else '-'}")


def main() -> None:
    print("=" * 45)
    print("        JEU DU PENDU RESEAU (CLI)        ")
    print("=" * 45)

    host = input("Serveur [127.0.0.1] : ").strip() or "127.0.0.1"
    port_input = input("Port [8888] : ").strip() or "8888"
    port = int(port_input)

    client = GameClient(host, port)
    try:
        client.connect()
    except (ConnectionError, OSError) as e:
        print(f"[ERREUR] Impossible de joindre le serveur {host}:{port} : {e}")
        sys.exit(1)

    # Vérification d'une session sauvegardée
    resume_choice = "n"
    if client.load_session("session.json"):
        resume_choice = input(f"Session précédente trouvée ({client.player_name}). Reprendre ? (O/n) : ").strip().lower()

    if resume_choice in ("o", "oui", "y", "yes"):
        print("[RESUME] Reprise de la session...")
        resp = client.resume()
        if resp.type == "ERROR":
            print(f"Impossible de reprendre la session : {resp.payload.get('message')}. Démarrage d'une nouvelle session.")
            player = input("Pseudo : ").strip() or "Joueur"
            client.hello(player)
            resp = client.new_game()
        elif resp.payload.get("status") == "IDLE":
            print("Session restaurée. Prêt pour une nouvelle partie.")
            resp = client.new_game()
    else:
        player = input("Pseudo : ").strip() or "Joueur"
        client.hello(player)
        client.save_session("session.json")
        resp = client.new_game()

    if resp.type == "ERROR":
        print("Erreur :", resp.payload.get("message"))
        client.close()
        return

    show_state(resp)

    try:
        while resp.payload.get("status") == "EN_COURS":
            choice = input("\nLettre (ou '!quit' pour abandonner, '!retry' pour renvoyer) : ").strip().upper()
            if not choice:
                continue

            if choice == "!QUIT":
                resp = client.quit_game()
                break
            elif choice == "!RETRY":
                resp = client.retry_last()
            else:
                resp = client.guess(choice[0])

            if resp.type == "ERROR":
                print(f"[ERREUR APPLICATIVE] {resp.payload.get('code')} : {resp.payload.get('message')}")
                continue

            show_state(resp)

        status = resp.payload.get("status")
        secret = resp.payload.get("secret_word")
        if status == "GAGNE":
            print("\n🎉 Bravo, vous avez gagné !")
        elif status == "PERDU":
            print(f"\n💀 Perdu ! Le mot secret était : {secret}")
        elif status == "ABANDONNE" or resp.type == "BYE":
            print("\nPartie abandonnée.")

    except (ConnectionError, OSError) as e:
        print("\n[ERREUR RESEAU] Problème de connexion :", e)
    finally:
        client.close()


if __name__ == "__main__":
    main()