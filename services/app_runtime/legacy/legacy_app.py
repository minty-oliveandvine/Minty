"""Compatibility shim for legacy imports."""

from services.app_runtime.legacy.compat import app, login_manager
from services.auth.session import load_user
from services.helpers.formatter import clock, comma_format, day, money

app.add_template_filter(comma_format, "comma_format")
app.add_template_filter(money, "money")
app.add_template_filter(day, "day")
app.add_template_filter(clock, "clock")
login_manager.user_loader(load_user)
