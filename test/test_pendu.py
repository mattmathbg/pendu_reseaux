import core.pendu

pendu = core.pendu.Pendu("python", max_errors=6)

def test_initial_state():
    assert pendu.state == core.pendu.GameState.IN_PROGRESS
    assert pendu.current_errors == 0
    assert pendu.guessed_letters == set()
    assert pendu.secret_word == "PYTHON"
