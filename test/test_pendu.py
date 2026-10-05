import pytest
from core.pendu import (
    Pendu,
    GameState,
    InvalidLetterError,
    InvalidStateError,
    LetterAlreadyTriedError,
)

@pytest.fixture
def game() -> Pendu:
    return Pendu("PYTHON", max_errors=3)

def test_initial_state(game: Pendu):
    assert game.state == GameState.IN_PROGRESS
    assert game.current_errors == 0
    assert game.guessed_letters == set()
    assert game.secret_word == "PYTHON"
    assert game.get_masked_word() == "_ _ _ _ _ _"
    assert not game.is_finished()

def test_guess_correct(game: Pendu):
    assert game.guess("p") is True
    assert "P" in game.guessed_letters
    assert game.current_errors == 0
    assert game.get_masked_word() == "P _ _ _ _ _"

def test_guess_wrong(game: Pendu):
    assert game.guess("z") is False
    assert "Z" in game.guessed_letters
    assert game.current_errors == 1
    assert game.state == GameState.IN_PROGRESS

def test_victory(game: Pendu):
    for char in ["P", "Y", "T", "H", "O", "N"]:
        game.guess(char)
    assert game.state == GameState.WON
    assert game.is_finished()
    assert game.get_masked_word() == "P Y T H O N"

def test_loss(game: Pendu):
    game.guess("A")
    game.guess("B")
    game.guess("C")
    assert game.state == GameState.LOST
    assert game.is_finished()

def test_already_tried_exception(game: Pendu):
    game.guess("P")
    with pytest.raises(LetterAlreadyTriedError):
        game.guess("P")

def test_invalid_input_exception(game: Pendu):
    with pytest.raises(InvalidLetterError):
        game.guess("1")
    with pytest.raises(InvalidLetterError):
        game.guess("AB")

def test_action_after_game_over(game: Pendu):
    game.guess("A")
    game.guess("B")
    game.guess("C")  # max_errors atteint
    with pytest.raises(InvalidStateError):
        game.guess("P")