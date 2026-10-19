import tkinter as tk
from string import ascii_lowercase
from tkinter import messagebox, simpledialog

from client.connection import GameClient

END_MESSAGES = {"GAGNE": "Bravo, gagné !", "PERDU": "Perdu...", "ABANDONNE": "Partie abandonnée."}


class HangmanApp:
    def __init__(self, root: tk.Tk, client: GameClient) -> None:
        self.root = root
        self.client = client
        root.title("Pendu en réseau")

        self.word_var = tk.StringVar(value="")
        self.info_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.word_var, font=("Courier", 28)).pack(padx=20, pady=10)
        tk.Label(root, textvariable=self.info_var).pack()

        grid = tk.Frame(root)
        grid.pack(padx=10, pady=10)
        self.buttons = {}
        for i, letter in enumerate(ascii_lowercase):
            btn = tk.Button(grid, text=letter.upper(), width=3,
                            command=lambda l=letter: self.play(l))
            btn.grid(row=i // 9, column=i % 9, padx=1, pady=1)
            self.buttons[letter] = btn

        tk.Button(root, text="Abandonner", command=self.quit_game).pack(pady=(0, 10))

    def start(self, player: str) -> None:
        resp = self.client.new_game(player)
        self.update_from(resp)

    def play(self, letter: str) -> None:
        self.update_from(self.client.guess(letter))

    def quit_game(self) -> None:
        self.update_from(self.client.quit_game())

    def update_from(self, resp) -> None:
        if resp.type == "ERROR":
            messagebox.showwarning("Erreur", f"{resp.payload['code']} : {resp.payload['message']}")
            return
        p = resp.payload
        self.word_var.set(" ".join(p["word"]))
        self.info_var.set(f"Essais restants : {p['remaining']}")
        for letter in p.get("guessed", []):
            if letter in self.buttons:
                self.buttons[letter].config(state="disabled")
        if p["state"] != "EN_COURS":
            for btn in self.buttons.values():
                btn.config(state="disabled")
            messagebox.showinfo("Fin de partie", END_MESSAGES[p["state"]])


def main() -> None:
    root = tk.Tk()
    root.withdraw()  # on cache la fenêtre le temps des questions
    host = simpledialog.askstring("Serveur", "Adresse :", initialvalue="127.0.0.1") or "127.0.0.1"
    port = simpledialog.askinteger("Serveur", "Port :", initialvalue=8888) or 8888
    player = simpledialog.askstring("Joueur", "Pseudo :") or "Joueur"

    client = GameClient(host, port)
    try:
        client.connect()
    except OSError as e:
        messagebox.showerror("Connexion impossible", str(e))
        return

    root.deiconify()
    app = HangmanApp(root, client)
    app.start(player)
    root.protocol("WM_DELETE_WINDOW", lambda: (client.close(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()