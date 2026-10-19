from client.connection import GameClient


def show_state(resp) -> None:
    p = resp.payload
    print(f"\nMot : {' '.join(p['word'])}")
    print(f"Essais restants : {p['remaining']}")
    print(f"Lettres jouées : {', '.join(p.get('guessed', [])) or '-'}")


def main() -> None:
    host = input("Serveur [127.0.0.1] : ").strip() or "127.0.0.1"
    port = int(input("Port [8888] : ").strip() or 8888)
    player = input("Pseudo : ").strip() or "Joueur"

    client = GameClient(host, port)
    try:
        client.connect()
        resp = client.new_game(player)
        if resp.type == "ERROR":
            print("Erreur :", resp.payload["message"])
            return
        show_state(resp)

        while resp.payload["state"] == "EN_COURS":
            choice = input("\nLettre (ou '!quit' pour abandonner) : ").strip().lower()
            if choice == "!quit":
                resp = client.quit_game()
            else:
                resp = client.guess(choice)

            if resp.type == "ERROR":
                # erreur applicative : on affiche, on continue la partie
                print(f"Erreur {resp.payload['code']} : {resp.payload['message']}")
                resp.payload.setdefault("state", "EN_COURS")
                continue
            show_state(resp)

        final = resp.payload["state"]
        print({"GAGNE": "Bravo, gagné !", "PERDU": "Perdu...", "ABANDONNE": "Partie abandonnée."}[final])
    except (ConnectionError, OSError) as e:
        print("Problème de connexion :", e)
    finally:
        client.close()


if __name__ == "__main__":
    main()