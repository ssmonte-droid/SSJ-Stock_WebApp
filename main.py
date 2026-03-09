from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

app = Flask(__name__)

# SECRET KEY stored in .env file for security
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

# MYSQL DATABASE CONNECTION
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_NAME = os.getenv("DB_NAME")
DB_HOST = os.getenv("DB_HOST")

app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# EXTENSIONS
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return Users.query.get(int(user_id))

# USER MODEL
class Users(UserMixin, db.Model):

    __tablename__ = "users"
    
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(250), unique=True, nullable=False)

    password = db.Column(db.String(250), nullable=False)

    role = db.Column(db.String(50), default="user", nullable=False)

    # Stores the user's current account balance
    balance = db.Column(db.Float, default=0)


# TRANSACTIONS TABLE
class Transactions(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    type = db.Column(db.String(50), nullable=False)  # deposit or withdraw

    amount = db.Column(db.Float, nullable=False)

    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

# STOCK TABLE
class Stocks(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    symbol = db.Column(db.String(10), unique=True, nullable=False)

    company_name = db.Column(db.String(200), nullable=False)

    price = db.Column(db.Float, nullable=False)

    available_shares = db.Column(db.Integer, nullable=False)

# PORTFOLIO TABLE
class Portfolio(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    stock_id = db.Column(db.Integer, db.ForeignKey("stocks.id"), nullable=False)

    shares = db.Column(db.Integer, nullable=False)


# CREATE TABLES
with app.app_context():
    db.create_all()

# BUY STOCK
# Lets a user buy shares if they have enough money and stock is available
@app.route("/buy/<int:stock_id>", methods=["POST"])
@login_required
def buy(stock_id):

    stock = Stocks.query.get(stock_id)

    shares = int(request.form.get("shares", 0))

    total_price = stock.price * shares

    if current_user.balance < total_price:
        flash("Not enough money to complete this purchase.")
        return redirect(url_for("home"))

    if stock.available_shares < shares:
        flash("Not enough stock available to complete this purchase.")
        return redirect(url_for("home"))

    current_user.balance -= total_price
    stock.available_shares -= shares

    portfolio = Portfolio.query.filter_by(
        user_id=current_user.id,
        stock_id=stock.id
    ).first()

    if portfolio:
        portfolio.shares += shares
    else:
        portfolio = Portfolio(
            user_id=current_user.id,
            stock_id=stock.id,
            shares=shares
        )
        db.session.add(portfolio)

    transaction = Transactions(
        user_id=current_user.id,
        type="buy",
        amount=total_price
    )

    db.session.add(transaction)
    db.session.commit()

    return redirect(url_for("home"))

# SELL STOCK
# Lets a user sell shares they already own
@app.route("/sell/<int:stock_id>", methods=["POST"])
@login_required
def sell(stock_id):

    stock = Stocks.query.get(stock_id)

    shares = int(request.form.get("shares", 0))

    portfolio = Portfolio.query.filter_by(
        user_id=current_user.id,
        stock_id=stock.id
    ).first()

    if not portfolio or portfolio.shares < shares:
        flash("You do not own enough shares to complete this sale.")
        return redirect(url_for("home"))

    total_price = stock.price * shares

    current_user.balance += total_price
    stock.available_shares += shares

    portfolio.shares -= shares

    if portfolio.shares == 0:
        db.session.delete(portfolio)

    transaction = Transactions(
        user_id=current_user.id,
        type="sell",
        amount=total_price
    )

    db.session.add(transaction)
    db.session.commit()

    return redirect(url_for("home"))

# CREATE STOCK (ADMIN ONLY)
@app.route("/create_stock", methods=["GET", "POST"])
@login_required
def create_stock():

    # Only admins can create stocks
    if current_user.role != "admin":
        return redirect(url_for("home"))

    if request.method == "POST":

        symbol = request.form.get("symbol")
        company_name = request.form.get("company_name")
        price = float(request.form.get("price"))
        available_shares = int(request.form.get("available_shares"))

        new_stock = Stocks(
            symbol=symbol,
            company_name=company_name,
            price=price,
            available_shares=available_shares
        )

        db.session.add(new_stock)
        db.session.commit()

        return redirect(url_for("home"))

    return render_template("create_stock.html")


# DEPOSIT ROUTE
@app.route("/deposit", methods=["POST"])
@login_required
def deposit():

    amount = float(request.form.get("amount", 0))

    if amount <= 0:
        flash("Invalid amount.")
        return redirect(url_for("home"))

    # Add money to user balance
    current_user.balance += amount

    transaction = Transactions(
        user_id=current_user.id,
        type="deposit",
        amount=amount
    )

    db.session.add(transaction)
    db.session.commit()

    return redirect(url_for("home"))

# WITHDRAW ROUTE
@app.route("/withdraw", methods=["POST"])
@login_required
def withdraw():

    amount = float(request.form.get("amount", 0))

    if amount <= 0:
        flash("Invalid amount.")
        return redirect(url_for("home"))

    if current_user.balance >= amount:

        current_user.balance -= amount

        transaction = Transactions(
            user_id=current_user.id,
            type="withdraw",
            amount=amount
        )

        db.session.add(transaction)
        db.session.commit()

    return redirect(url_for("home"))


# HOME PAGE
@app.route("/")
@login_required
def home():

    stocks = Stocks.query.all()

    user_portfolio = Portfolio.query.filter_by(user_id=current_user.id).all()

    portfolio_dict = {}
    portfolio_value = 0

    for item in user_portfolio:

        portfolio_dict[item.stock_id] = item.shares

        stock = Stocks.query.get(item.stock_id)

        portfolio_value += item.shares * stock.price
    return render_template(
    "home.html",
    stocks=stocks,
    portfolio=portfolio_dict,
    portfolio_value=portfolio_value
)
#transactions page to show user transaction history
@app.route("/transactions")
@login_required
def transactions():

    history = Transactions.query.filter_by(
        user_id=current_user.id
    ).order_by(Transactions.timestamp.desc()).all()

    return render_template(
        "transactions.html",
        history=history
    )

# REGISTER USER
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")

        new_user = Users(
            username=username,
            password=hashed_password,
            role="user"
        )

        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for("login"))

    return render_template("sign_up.html")


# LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        user = Users.query.filter_by(username=username).first()

        if user and bcrypt.check_password_hash(user.password, password):

            login_user(user)

            return redirect(url_for("home"))

    return render_template("login.html")


# LOGOUT
@app.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)