from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[
        DataRequired(message="Saisissez votre adresse e-mail."),
        Email(message="Saisissez une adresse e-mail valide."),
    ])
    password = PasswordField("Mot de passe", validators=[
        DataRequired(message="Saisissez votre mot de passe."),
    ])
    submit = SubmitField("Se connecter")
