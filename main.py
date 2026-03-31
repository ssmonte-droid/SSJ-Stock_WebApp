from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
from datetime import datetime, time
import os

load_dotenv()

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_NAME = os.getenv("DB_NAME")
DB_HOST = os.getenv("DB_HOST")

app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = ""


@login_manager.user_loader
def load_user(user_id):
    return Users.query.get(int(user_id))

# MODELS
class Users(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    username = db.Column(db.String(250), unique=True, nullable=False)
    password = db.Column(db.String(250), nullable=False)
    role = db.Column(db.String(50), default="user", nullable=False)
    balance = db.Column(db.Float, default=0.0)


class Transactions(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())


class Stocks(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(10), unique=True, nullable=False)
    company_name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    available_shares = db.Column(db.Integer, nullable=False)


class Portfolio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    stock_id = db.Column(db.Integer, db.ForeignKey("stocks.id"), nullable=False)
    shares = db.Column(db.Integer, nullable=False)


class PendingOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    stock_id = db.Column(db.Integer, db.ForeignKey("stocks.id"), nullable=False)
    order_type = db.Column(db.String(10), nullable=False)  # buy or sell
    shares = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="queued", nullable=False)  # queued, executed, failed
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    executed_at = db.Column(db.DateTime, nullable=True)
    failure_reason = db.Column(db.String(255), nullable=True)

class MarketSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    open_time = db.Column(db.Time, nullable=False, default=time(9, 30))
    close_time = db.Column(db.Time, nullable=False, default=time(16, 0))
    timezone = db.Column(db.String(100), nullable=False, default="America/New_York")

    monday = db.Column(db.Boolean, default=True, nullable=False)
    tuesday = db.Column(db.Boolean, default=True, nullable=False)
    wednesday = db.Column(db.Boolean, default=True, nullable=False)
    thursday = db.Column(db.Boolean, default=True, nullable=False)
    friday = db.Column(db.Boolean, default=True, nullable=False)
    saturday = db.Column(db.Boolean, default=False, nullable=False)
    sunday = db.Column(db.Boolean, default=False, nullable=False)


with app.app_context():
    db.create_all()

    settings = MarketSettings.query.first()
    if not settings:
        settings = MarketSettings(
            open_time=time(9, 30),
            close_time=time(16, 0),
            timezone="America/New_York",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=False,
            sunday=False
        )
        db.session.add(settings)
        db.session.commit()

# HELPERS
def get_market_settings():
    return MarketSettings.query.first()


def get_market_now():
    settings = get_market_settings()
    return datetime.now(ZoneInfo(settings.timezone))


def is_market_open():
    settings = get_market_settings()
    now_local = get_market_now()

    allowed_days = {
        0: settings.monday,
        1: settings.tuesday,
        2: settings.wednesday,
        3: settings.thursday,
        4: settings.friday,
        5: settings.saturday,
        6: settings.sunday
    }

    if not allowed_days[now_local.weekday()]:
        return False

    return settings.open_time <= now_local.time() <= settings.close_time


def market_status_text():
    settings = get_market_settings()
    now_local = get_market_now()
    return now_local.strftime("%A, %I:%M %p") + f" ({settings.timezone})"


def queue_order(user_id, stock_id, order_type, shares):
    order = PendingOrder(
        user_id=user_id,
        stock_id=stock_id,
        order_type=order_type,
        shares=shares,
        status="queued"
    )
    db.session.add(order)
    db.session.commit()


def process_pending_orders():
    if not is_market_open():
        return

    queued_orders = PendingOrder.query.filter_by(status="queued").order_by(PendingOrder.created_at.asc()).all()

    for order in queued_orders:
        user = Users.query.get(order.user_id)
        stock = Stocks.query.get(order.stock_id)

        if not user or not stock:
            order.status = "failed"
            order.failure_reason = "User or stock not found."
            order.executed_at = datetime.utcnow()
            continue

        if order.order_type == "buy":
            total_price = stock.price * order.shares

            if user.balance < total_price:
                order.status = "failed"
                order.failure_reason = "Insufficient funds at execution time."
                order.executed_at = datetime.utcnow()
                continue

            if stock.available_shares < order.shares:
                order.status = "failed"
                order.failure_reason = "Insufficient stock available at execution time."
                order.executed_at = datetime.utcnow()
                continue

            user.balance -= total_price
            stock.available_shares -= order.shares

            portfolio = Portfolio.query.filter_by(
                user_id=user.id,
                stock_id=stock.id
            ).first()

            if portfolio:
                portfolio.shares += order.shares
            else:
                portfolio = Portfolio(
                    user_id=user.id,
                    stock_id=stock.id,
                    shares=order.shares
                )
                db.session.add(portfolio)

            transaction = Transactions(
                user_id=user.id,
                type="buy",
                amount=total_price
            )
            db.session.add(transaction)

            order.status = "executed"
            order.executed_at = datetime.utcnow()

        elif order.order_type == "sell":
            portfolio = Portfolio.query.filter_by(
                user_id=user.id,
                stock_id=stock.id
            ).first()

            if not portfolio or portfolio.shares < order.shares:
                order.status = "failed"
                order.failure_reason = "Not enough shares at execution time."
                order.executed_at = datetime.utcnow()
                continue

            total_price = stock.price * order.shares

            user.balance += total_price
            stock.available_shares += order.shares
            portfolio.shares -= order.shares

            if portfolio.shares == 0:
                db.session.delete(portfolio)

            transaction = Transactions(
                user_id=user.id,
                type="sell",
                amount=total_price
            )
            db.session.add(transaction)

            order.status = "executed"
            order.executed_at = datetime.utcnow()

    db.session.commit()


# PUBLIC LANDING PAGE
@app.route("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


# DASHBOARD
@app.route("/dashboard")
@login_required
def dashboard():
    process_pending_orders()

    stocks = Stocks.query.all()
    user_portfolio = Portfolio.query.filter_by(user_id=current_user.id).all()
    pending_orders = PendingOrder.query.filter_by(user_id=current_user.id, status="queued").order_by(PendingOrder.created_at.desc()).all()

    portfolio_dict = {}
    portfolio_value = 0

    for item in user_portfolio:
        portfolio_dict[item.stock_id] = item.shares
        stock = Stocks.query.get(item.stock_id)
        if stock:
            portfolio_value += item.shares * stock.price

    return render_template(
        "home.html",
        stocks=stocks,
        portfolio=portfolio_dict,
        portfolio_value=portfolio_value,
        market_open=is_market_open(),
        market_time=market_status_text(),
        pending_orders=pending_orders
    )


# BUY
@app.route("/buy/<int:stock_id>", methods=["POST"])
@login_required
def buy(stock_id):
    stock = Stocks.query.get(stock_id)
    shares = int(request.form.get("shares", 0))

    if not stock or shares <= 0:
        flash("Invalid stock or share amount.")
        return redirect(url_for("dashboard"))

    if not is_market_open():
        queue_order(current_user.id, stock.id, "buy", shares)
        flash("Market is closed. Your buy order has been queued.")
        return redirect(url_for("dashboard"))

    total_price = stock.price * shares

    if current_user.balance < total_price:
        flash("Not enough money to complete this purchase.")
        return redirect(url_for("dashboard"))

    if stock.available_shares < shares:
        flash("Not enough stock available to complete this purchase.")
        return redirect(url_for("dashboard"))

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

    flash("Buy order executed successfully.")
    return redirect(url_for("dashboard"))

# SELL
@app.route("/sell/<int:stock_id>", methods=["POST"])
@login_required
def sell(stock_id):
    stock = Stocks.query.get(stock_id)
    shares = int(request.form.get("shares", 0))

    if not stock or shares <= 0:
        flash("Invalid stock or share amount.")
        return redirect(url_for("dashboard"))

    if not is_market_open():
        queue_order(current_user.id, stock.id, "sell", shares)
        flash("Market is closed. Your sell order has been queued.")
        return redirect(url_for("dashboard"))

    portfolio = Portfolio.query.filter_by(
        user_id=current_user.id,
        stock_id=stock.id
    ).first()

    if not portfolio or portfolio.shares < shares:
        flash("You do not own enough shares to complete this sale.")
        return redirect(url_for("dashboard"))

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

    flash("Sell order executed successfully.")
    return redirect(url_for("dashboard"))

# DELETE QUEUED ORDER
@app.route("/delete_order/<int:order_id>")
@login_required
def delete_order(order_id):

    order = PendingOrder.query.get(order_id)

    if not order:
        flash("Order not found.")
        return redirect(url_for("dashboard"))

    if order.user_id != current_user.id:
        return redirect(url_for("dashboard"))

    if order.status != "queued":
        flash("Cannot delete executed order.")
        return redirect(url_for("dashboard"))

    db.session.delete(order)
    db.session.commit()

    flash("Queued order deleted.")

    return redirect(url_for("dashboard"))

# CREATE STOCK
@app.route("/create_stock", methods=["GET", "POST"])
@login_required
def create_stock():
    if current_user.role != "admin":
        return redirect(url_for("dashboard"))

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

        flash("Stock created successfully.")
        return redirect(url_for("dashboard"))

    return render_template("create_stock.html")


# DELETE STOCK
@app.route("/delete_stock/<int:id>")
@login_required
def delete_stock(id):
    if current_user.role != "admin":
        return redirect(url_for("dashboard"))

    stock = Stocks.query.get(id)

    if stock:
        db.session.delete(stock)
        db.session.commit()
        flash("Stock deleted successfully.")

    return redirect(url_for("dashboard"))


# EDIT STOCK
@app.route("/edit_stock/<int:id>", methods=["GET", "POST"])
@login_required
def edit_stock(id):
    if current_user.role != "admin":
        return redirect(url_for("dashboard"))

    stock = Stocks.query.get(id)

    if not stock:
        flash("Stock not found.")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        stock.symbol = request.form["symbol"]
        stock.company_name = request.form["company_name"]
        stock.price = float(request.form["price"])
        stock.available_shares = int(request.form["available_shares"])

        db.session.commit()
        flash("Stock updated successfully.")
        return redirect(url_for("dashboard"))

    return render_template("edit_stock.html", stock=stock)


# DEPOSIT
@app.route("/deposit", methods=["POST"])
@login_required
def deposit():
    amount = float(request.form.get("amount", "0").replace(",", ""))

    if amount <= 0:
        flash("Invalid amount.")
        return redirect(url_for("dashboard"))

    current_user.balance += amount

    transaction = Transactions(
        user_id=current_user.id,
        type="deposit",
        amount=amount
    )

    db.session.add(transaction)
    db.session.commit()

    flash("Deposit successful.")
    return redirect(url_for("dashboard"))


# WITHDRAW
@app.route("/withdraw", methods=["POST"])
@login_required
def withdraw():
    amount = float(request.form.get("amount", "0").replace(",", ""))

    if amount <= 0:
        flash("Invalid amount.")
        return redirect(url_for("dashboard"))

    if current_user.balance >= amount:
        current_user.balance -= amount

        transaction = Transactions(
            user_id=current_user.id,
            type="withdraw",
            amount=amount
        )

        db.session.add(transaction)
        db.session.commit()

        flash("Withdrawal successful.")
    else:
        flash("Insufficient balance.")

    return redirect(url_for("dashboard"))


# TRANSACTIONS
@app.route("/transactions")
@login_required
def transactions():
    history = Transactions.query.filter_by(
        user_id=current_user.id
    ).order_by(Transactions.timestamp.desc()).all()

    return render_template("transactions.html", history=history)


# SIGN UP
@app.route("/sign_up", methods=["GET", "POST"])
def register():

    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")

        existing_user = Users.query.filter(
            (Users.username == username) | (Users.email == email)
        ).first()

        if existing_user:
            flash("Username or email already exists.")
            return redirect(url_for("sign_up"))

        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")

        new_user = Users(
            full_name=full_name,
            email=email,
            username=username,
            password=hashed_password,
            role="user"
        )

        db.session.add(new_user)
        db.session.commit()

        flash("Account created successfully. Please log in.")
        return redirect(url_for("login"))

    return render_template("sign_up.html")

# LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = Users.query.filter_by(username=username).first()

        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.")

    return render_template("login.html")


# LOGOUT
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("landing"))

@app.route("/market_settings", methods=["GET", "POST"])
@login_required
def market_settings():
    if current_user.role != "admin":
        return redirect(url_for("dashboard"))

    settings = MarketSettings.query.first()

    if request.method == "POST":
        open_time_str = request.form.get("open_time")
        close_time_str = request.form.get("close_time")
        timezone_str = request.form.get("timezone")

        new_open = datetime.strptime(open_time_str, "%H:%M").time()
        new_close = datetime.strptime(close_time_str, "%H:%M").time()

        if new_open >= new_close:
            flash("Open time must be earlier than close time.")
            return redirect(url_for("market_settings"))

        settings.open_time = new_open
        settings.close_time = new_close
        settings.timezone = timezone_str

        settings.monday = "monday" in request.form
        settings.tuesday = "tuesday" in request.form
        settings.wednesday = "wednesday" in request.form
        settings.thursday = "thursday" in request.form
        settings.friday = "friday" in request.form
        settings.saturday = "saturday" in request.form
        settings.sunday = "sunday" in request.form

        db.session.commit()
        flash("Market settings updated successfully.")
        return redirect(url_for("market_settings"))

    return render_template("market_settings.html", settings=settings)


if __name__ == "__main__":
    app.run(debug=True)