import re
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, ValidationError


def _validate_identifier(form, field):
    raw = (field.data or "").strip()
    if not raw:
        raise ValidationError("Saisissez votre numéro de téléphone ou votre adresse e-mail.")
    digits = re.sub(r"\D", "", raw)
    is_phone = len(digits) >= 8
    is_email = "@" in raw and "." in raw.split("@")[-1] and len(raw) >= 5
    if not is_phone and not is_email:
        raise ValidationError("Saisissez un numéro de téléphone valide ou une adresse e-mail valide.")


class LoginForm(FlaskForm):
    email = StringField("Email ou Téléphone", validators=[
        DataRequired(message="Saisissez votre numéro de téléphone ou votre adresse e-mail."),
        _validate_identifier,
    ])
    password = PasswordField("Mot de passe", validators=[
        DataRequired(message="Saisissez votre mot de passe."),
    ])
    submit = SubmitField("Se connecter")


class VendorLoginForm(FlaskForm):
    phone = StringField("Numéro de téléphone", validators=[
        DataRequired(message="Saisissez votre numéro de téléphone."),
    ])
    password = PasswordField("Mot de passe", validators=[
        DataRequired(message="Saisissez votre mot de passe."),
    ])
    submit = SubmitField("Se connecter à mon espace vendeur")
