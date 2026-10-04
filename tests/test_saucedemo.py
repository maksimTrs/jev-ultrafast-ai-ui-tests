"""Happy paths on saucedemo. The agent only gets goals; the verdict comes from reading the real page.

Goals are short and name each step ("enter ..., then click ..."). The 322M decision model is phrasing-sensitive
("Log in with ..." makes it press Login before filling the form) and loses track of long multi-step goals,
so the checkout is a chain of short goals in one tab, with a check of the real page after each.
"""

import pytest

pytestmark = pytest.mark.live

LOGIN = "Enter username standard_user and password secret_sauce, then click Login."


def test_login(jev):
    result, page = jev.start("/", LOGIN, max_actions=6)

    assert page.evaluate("location.pathname") == "/inventory.html", result.outcome
    assert page.evaluate("document.querySelectorAll('.inventory_item').length") == 6


def test_add_backpack_to_cart(jev, logged_in):
    result, page = jev.start("/inventory.html", "Add Sauce Labs Backpack to the cart.", max_actions=4)

    assert page.evaluate("document.querySelector('.shopping_cart_badge')?.textContent") == "1", result.outcome
    assert page.evaluate("localStorage.getItem('cart-contents')") == "[4]"  # 4 is the Backpack's item id


def test_low_confidence_step_is_not_executed(jev, logged_in):
    # Two T-shirts are for sale, so the goal is ambiguous: the model spreads its choice (~0.11 at best) below
    # MIN_PROBABILITY. Here the agent's own stop is what is checked, so its status is part of the verdict.
    result, page = jev.start("/inventory.html", "Add a T-shirt to the cart.", max_actions=4)

    assert result.status == "blocked", result.outcome
    assert result.error.startswith("probability "), result.outcome
    assert page.evaluate("localStorage.getItem('cart-contents')") is None  # nothing was added


def test_full_checkout(jev):
    result, page = jev.start("/", LOGIN, max_actions=6)
    assert page.evaluate("location.pathname") == "/inventory.html", result.outcome

    result, page = jev.then("Add Sauce Labs Backpack to the cart.", max_actions=4)
    assert page.evaluate("localStorage.getItem('cart-contents')") == "[4]", result.outcome

    # "Open the cart" / "Go to the cart" make the model scroll; the icon's accessible name is "Cart, 1 items".
    result, page = jev.then("Click the shopping cart.", max_actions=3)
    assert page.evaluate("location.pathname") == "/cart.html", result.outcome

    # No values in the goal: the text model invents them, so the check is that every field holds what was typed.
    result, page = jev.then("Click Checkout, then enter first name, last name and postal code.", max_actions=6)
    assert page.evaluate("location.pathname") == "/checkout-step-one.html", result.outcome
    fields = page.evaluate("['first-name', 'last-name', 'postal-code'].map(id => document.getElementById(id).value)")
    typed = [step["text"] for step in result.steps if step["operation"] == "TYPE_TEXT"]
    assert all(fields) and sorted(fields) == sorted(typed), (fields, typed, result.outcome)

    # After the last field the model answers DONE rather than submitting, so submitting is its own goal.
    result, page = jev.then("Click Continue.", max_actions=3)
    assert page.evaluate("location.pathname") == "/checkout-step-two.html", result.outcome

    result, page = jev.then("Click Finish.", max_actions=3)
    assert page.evaluate("location.pathname") == "/checkout-complete.html", result.outcome
    assert page.evaluate("document.querySelector('.complete-header')?.textContent") == "Thank you for your order!"
