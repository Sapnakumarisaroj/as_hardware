from django.core.exceptions import ValidationError


class LetterAndDigitValidator:
    """Require at least one letter and one digit (in addition to Django's length/common/numeric checks)."""

    def validate(self, password, user=None):
        if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
            raise ValidationError(
                "Password must contain at least one letter and one number.", code="password_no_letter_or_digit"
            )

    def get_help_text(self):
        return "Your password must contain at least one letter and one number."
