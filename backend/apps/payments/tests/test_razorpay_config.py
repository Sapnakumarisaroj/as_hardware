"""Razorpay Test Mode configuration: the check command never prints secrets; development refuses live keys."""

import os
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest
from django.core.management import call_command

from integrations.payments.base import GatewayRejected

SECRET = "test-secret-value-never-printed"


def run_check(*args):
    out, err = StringIO(), StringIO()
    try:
        call_command("razorpay_check", *args, stdout=out, stderr=err)
        code = 0
    except SystemExit as exc:
        code = exc.code
    return code, out.getvalue() + err.getvalue()


def test_reports_test_mode_without_printing_secrets(settings):
    settings.PAYMENT_PROVIDER = "razorpay"
    settings.RAZORPAY_KEY_ID = "rzp_test_ABCDEF123456"
    settings.RAZORPAY_KEY_SECRET = SECRET
    settings.RAZORPAY_WEBHOOK_SECRET = SECRET + "-webhook"
    code, text = run_check()
    assert code == 0 and "TEST mode" in text and "rzp_test_…" in text
    assert SECRET not in text and "ABCDEF123456" not in text


def test_missing_keys_fail(settings):
    settings.PAYMENT_PROVIDER = "razorpay"
    settings.RAZORPAY_KEY_ID = ""
    settings.RAZORPAY_KEY_SECRET = ""
    code, text = run_check()
    assert code == 1 and "both needed" in text


def test_ping_reports_rejected_keys(settings):
    settings.PAYMENT_PROVIDER = "razorpay"
    settings.RAZORPAY_KEY_ID = "rzp_test_ABCDEF123456"
    settings.RAZORPAY_KEY_SECRET = SECRET
    with mock.patch("integrations.payments.razorpay.RazorpayClient.request", side_effect=GatewayRejected("Authentication failed")):
        code, text = run_check("--ping")
    assert code == 1 and "rejected the keys" in text and SECRET not in text


@pytest.mark.parametrize(("key", "refused"), [("rzp_live_ABCDEF123456", True), ("rzp_test_ABCDEF123456", False)])
def test_development_settings_refuse_live_keys(key, refused):
    backend = Path(__file__).resolve().parents[3]
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.dev", "DJANGO_ENV": "development",
           "PAYMENT_PROVIDER": "razorpay", "RAZORPAY_KEY_ID": key, "RAZORPAY_KEY_SECRET": "x"}  # fmt: skip
    result = subprocess.run(  # noqa: S603 — fixed interpreter and arguments
        [sys.executable, "-c", "import django; django.setup()"], cwd=backend, env=env, capture_output=True, text=True
    )
    assert (result.returncode != 0) is refused
    if refused:
        assert "Live Razorpay keys" in result.stderr
