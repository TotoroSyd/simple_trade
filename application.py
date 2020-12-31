import os

import datetime
import requests
import json

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd, lookup_test

# Configure application
app = Flask(__name__)

# Global variables
stock_found = False
API_KEY = os.environ.get('API_KEY')
T_API_KEY = os.environ.get('TPK')

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
# The directory where session files are stored. Default to use flask_session directory under current working directory.
app.config["SESSION_FILE_DIR"] = mkdtemp()
# Whether use permanent session or not, default to be True
# By default, all non-null sessions in Flask-Session are permanent.
# Therefore, we must set it to False so Session will expire when logging out
app.config["SESSION_PERMANENT"] = False
# Specifies which type of session interface to use. Builtin: null, redis, memcached, filesystem, mongodb, sqlalchemy
app.config["SESSION_TYPE"] = "filesystem"
# This class is used to add Server-side Session to one or more Flask applications.
# initialize the instance with a very specific Flask application
# Configure CS50 Library to use SQLite database
# #default from CS50 codebase
# db = SQL("sqlite:///finance.db")
# #When hosting with Heroku using Postgresql
db = SQL(os.getenv("DATABASE_URL"))

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    empty_porfolio = True
    # Return an array of object
    porfolio = db.execute("SELECT * FROM porfolio WHERE user_id = :user_id", user_id=session["user_id"])
    if not porfolio:
        return render_template("porfolio.html", today=(datetime.datetime.now()).strftime("%a, %d %B, %Y"), empty_porfolio=empty_porfolio)
    else:
        empty_porfolio = False

        # get the list of stock code to fetch live value pershare everytime this route runs
        porfolio_stock_list = ""
        # Return an array of object
        stock_code = db.execute("SELECT stock_code FROM porfolio WHERE user_id = :user_id", user_id=session["user_id"])
        for code in stock_code:
            porfolio_stock_list = porfolio_stock_list + ',' + (code["stock_code"])
        # prepare params for HTTP request to IEX
        payload = {'token': API_KEY, 'symbols': porfolio_stock_list, 'types':'quote'}
        # send batch request to IEX for value per share = latestPrice
        r = requests.get("https://cloud.iexapis.com/stable/stock/market/batch", params=payload)
        # convert HTTP response to JSON dict object
        r_json = json.loads(r.text)
        # print(r_json.keys())
        # collect the latestPrice from quote
        latest_price_dict = {}
        for k in r_json.keys():
            quote = r_json[k]['quote']
            latestPrice = float(quote["latestPrice"])
            latest_price_dict[k] = latestPrice
        # print(latest_price_dict)


        cash = db.execute("SELECT cash FROM users WHERE id = :id", id=session["user_id"])
        sum_val = cash[0]['cash']
        # Add comma and $ to price
        cash[0]['cash'] = usd(cash[0]['cash'])

        # update value_per_share, total_value with latestPrice
        for investment in porfolio:
            investment['value_per_share'] = latest_price_dict[(investment['stock_code'])]
            # Calculate updated total_value of stock_code and Format value as USD
            investment['total_value'] = (investment['value_per_share'] * investment['quantity'])
            sum_val = sum_val + investment['total_value']
            investment['total_value'] = usd(investment['total_value'])
            # After using int of value_per_share to calculate total_value, usd() formats value as USD
            investment['value_per_share'] = usd((investment['value_per_share']))
        # After using int of sum_val, usd() formats value as USD
        sum_val = usd(sum_val)
        # render page
        return render_template("porfolio.html", today=(datetime.datetime.now()).strftime("%a, %d %B, %Y"), porfolio=porfolio, cash=cash, empty_porfolio=empty_porfolio, sum_val=sum_val)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    buy_receipt_show = False
    disable_button = ""
    error = ""
    if request.method == "GET":
        return render_template("buy.html", buy_receipt_show=buy_receipt_show)
    else:
        if "buy" in request.form:
            # Allow showing confirmation div to confirm
            buy_receipt_show = True

            # Collect inputs from form
            stock_symbol = request.form.get("stockSymbolToBuy").upper()
            shares = int(request.form.get("numbersOfSharesToBuy"))
            bidding_value = int(request.form.get("biddingValue"))
            total = shares * bidding_value

            # Check cash balance sufficiency
            if total > session["cash"]:
                disable_button = "disabled"
                error = "insufficient"

            # Validate if code is correct on IEX
            # quote = {name:.., price:.., symbol:...}
            quote = lookup(stock_symbol)
            if not quote:
                disable_button = "disabled"
                error = "stock not found"

            # Render template
            return render_template("buy.html", quote=quote, shares=shares, bidding_value=bidding_value, total=total, buy_receipt_show=buy_receipt_show, disable_button=disable_button, error=error)
        elif "confirm_to_buy" in request.form:
            # Collect inputs from form
            name = request.form.get("name").upper()
            stock_symbol = request.form.get("stock_symbol")
            shares = int(request.form.get("shares"))
            bidding_value = int(request.form.get("bidding_value"))
            date = (datetime.datetime.now()).strftime("%d/%m/%Y")
            total = shares * bidding_value
            # print(name, stock_symbol, shares, bidding_value, date, total)

            # Update history table in db
            db.execute("INSERT INTO history (user_id, stock_code, quantity, val_per_share, date, type) VALUES (:user_id, :stock_code, :quantity, :val_per_share, :date, :type)", user_id=session["user_id"], stock_code=stock_symbol, quantity=shares, val_per_share=bidding_value, date=date, type="buy")
            # Update cash in users table in db
            updated_cash_balance = session["cash"] - total
            db.execute("UPDATE users SET cash = :updated_cash_balance WHERE id = :id", updated_cash_balance=updated_cash_balance, id=session["user_id"])
            # Update porfolio table in db
            available_shares = db.execute("SELECT quantity FROM porfolio WHERE (user_id=:user_id AND stock_code=:stock_code)", user_id=session["user_id"], stock_code=stock_symbol)
            # if the share hasn't been bought, INSERT
            if not available_shares:
                db.execute("INSERT INTO porfolio (company, stock_code, quantity, value_per_share, total_value, user_id) VALUES (:name, :stock_code, :quantity, :value_per_share, :total_value, :user_id)", user_id=session["user_id"], stock_code=stock_symbol, quantity=shares, name=name, value_per_share=bidding_value, total_value=total)
            else:
                updated_shares = available_shares[0]["quantity"] + shares
                db.execute("UPDATE porfolio SET quantity = :quantity WHERE (user_id=:user_id AND stock_code=:stock_code)", user_id=session["user_id"], stock_code=stock_symbol, quantity=updated_shares)
        return redirect("/")

@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    sell_receipt_show = False
    disable_button = ""
    error = ""
    if request.method == "GET":
        stock_code = db.execute("SELECT stock_code FROM porfolio WHERE user_id = :user_id", user_id=session["user_id"])
        # print(stock_code)
        return render_template("sell.html", sell_receipt_show=sell_receipt_show, stock_code=stock_code)
    else:
        if "sell" in request.form:
            # Allow showing confirmation div to confirm
            sell_receipt_show = True

            # Collect inputs from form
            stock_symbol = request.form.get("stockSymbolToSell").upper()
            shares = int(request.form.get("numberOfSharesToSell"))
            selling_value = int(request.form.get("sellingValue"))
            total = shares * selling_value

            # Check number of shares sufficiency in the account
            shares_record = db.execute("SELECT company, stock_code, quantity FROM porfolio WHERE user_id = :user_id", user_id=session["user_id"])
            current_shares = {}
            company_name = {}
            for record in shares_record:
                current_shares[record['stock_code']] = record['quantity']
                company_name[record['stock_code']] = record['company']
            # Check shares sufficiency
            if shares > current_shares[stock_symbol]:
                disable_button = "disabled"
                error = "insufficient_shares"
                # Render template
                return render_template("sell.html", stock_symbol=stock_symbol, shares=shares, selling_value=selling_value, total=total, sell_receipt_show=sell_receipt_show, disable_button=disable_button, error=error)
            else:
                # Render template
                company = company_name[stock_symbol]
                return render_template("sell.html", company=company, stock_symbol=stock_symbol, shares=shares, selling_value=selling_value, total=total, sell_receipt_show=sell_receipt_show, disable_button=disable_button, error=error)
        elif "confirm_to_sell" in request.form:
            # Collect inputs from form
            name = request.form.get("name").upper()
            stock_symbol = request.form.get("stock_symbol")
            shares = int(request.form.get("shares"))
            selling_value = int(request.form.get("selling_value"))
            date = (datetime.datetime.now()).strftime("%d/%m/%Y")
            total = shares * selling_value

            # Update history table in db
            db.execute("INSERT INTO history (user_id, stock_code, quantity, val_per_share, date, type) VALUES (:user_id, :stock_code, :quantity, :val_per_share, :date, :type)", user_id=session["user_id"], stock_code=stock_symbol, quantity=shares, val_per_share=selling_value, date=date, type="sell")
            # Update cash in users table in db
            updated_cash_balance = session["cash"] + total
            db.execute("UPDATE users SET cash = :updated_cash_balance WHERE id = :id", updated_cash_balance=updated_cash_balance, id=session["user_id"])
            # Update porfolio table in db
            available_shares = db.execute("SELECT quantity FROM porfolio WHERE (user_id=:user_id AND stock_code=:stock_code)", user_id=session["user_id"], stock_code=stock_symbol)
            updated_shares = available_shares[0]["quantity"] - shares
            # Only update if there are still the same shares in porfolio
            if updated_shares != 0:
                db.execute("UPDATE porfolio SET quantity = :quantity WHERE (user_id=:user_id AND stock_code=:stock_code)", user_id=session["user_id"], stock_code=stock_symbol, quantity=updated_shares)
            # Delete a share if nothing left
            else:
                db.execute("DELETE FROM porfolio WHERE (user_id=:user_id AND stock_code=:stock_code)", user_id=session["user_id"], stock_code=stock_symbol)
        return redirect("/")

@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    history = db.execute("SELECT * FROM history WHERE user_id= :user_id", user_id=session["user_id"])
    return render_template("history.html", history=history)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]
        session["cash"] = rows[0]["cash"]

        # Redirect user to home page
        return redirect("/quote")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    return render_template("quote.html")

@app.route("/search_stock", methods=["GET", "POST"])
def search_stock():
    """ Return stock name, company, value at open, current value """
    if request.method == "GET":
        return redirect("/quote")
    else:
        stock_found = True;
        stock_code = request.form.get("stock_code")
        quote = lookup(stock_code)
        quote['price'] = usd(quote['price'])

        return render_template("quote.html", quote=quote, stock_found = stock_found)

@app.route("/register", methods = ["GET", "POST"])
def register():
    """Register user"""
    return render_template("register.html")

@app.route("/create_account", methods=["GET","POST"])
def create_account():
    # #Temporary disabled because id in users table in DB has autoacr
    # user_id = (uuid.uuid1()).int
    username = request.form.get("username")
    email = request.form.get("email")
    new_password = request.form.get("new_password")
    # Hash password for security
    hash_new_password = generate_password_hash(new_password, method='pbkdf2:sha256', salt_length=8)
    # print(type(user_id), type(username), type(email), type(hash_new_password))
    # Add new user to users table in DB finance
    # db.execute("INSERT INTO users (id, username, hash, email) VALUES (:id, :username, :hash, :email)", id=user_id, username=username, hash=hash_new_password, email=email)
    db.execute("INSERT INTO users (username, hash, email) VALUES (:username, :hash, :email)", username=username, hash=hash_new_password, email=email)
    return redirect("/login")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
