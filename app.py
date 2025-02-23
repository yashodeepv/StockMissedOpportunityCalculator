from flask import Flask, render_template, request, jsonify
import math
import yfinance as yf 
import pandas as pd
import datetime
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

def format_rupee(number):
    number = int(number)
    if number < 1000:
        return f"₹{str(number)}"
    elif number < 100000:
        return f"₹{number // 1000},{number % 1000:03d}"
    elif number < 10000000:
        return f"₹{number // 100000},{number % 100000 // 1000:02d},{number % 1000:03d}"
    else:
        return f"₹{number // 10000000},{number % 10000000 // 100000:02d},{number % 100000 // 1000:02d},{number % 1000:03d}"



@app.route('/')
def index():
    today = datetime.date.today().strftime("%Y-%m-%d")
    return render_template("index.html", today=today)

@app.route('/calculate', methods=['POST'])
def calculate():
    data = request.get_json()
    app.logger.info("Received data: %s", data)
    
    stock_name = data.get('stock_ticker')
    start_date_str = data.get('start_date')
    end_date_str = data.get('end_date')
    frequency = data.get('frequency')            # "monthly" or "quarterly"
    investment_type = data.get('investment_type')  # "amount" or "shares"
    investment_mode = data.get('investment_mode')  # "Periodic" or "Lumpsum"
    
    try:
        investment_value = float(data.get('investment_value'))
    except:
        return jsonify({"error": "Invalid investment value."}), 400
    try:
        yearly_increment = float(data.get('yearly_increment')) / 100.0 if data.get('yearly_increment') else 0.0
    except:
        return jsonify({"error": "Invalid yearly increment."}), 400

    try:
        start_date = pd.to_datetime(start_date_str).date()
        end_date = pd.to_datetime(end_date_str).date()
    except Exception as e:
        return jsonify({"error": "Invalid date format."}), 400
    
    if start_date >= end_date:
        return jsonify({"error": "Start date must be before end date."}), 400
    if investment_value <= 0:
        return jsonify({"error": "Investment value must be positive."}), 400

    today_date = datetime.date.today()
    effective_end_date = end_date if end_date >= today_date else today_date

    ticker_obj = yf.Ticker(stock_name)
    price_data = ticker_obj.history(start=start_date, end=effective_end_date)
    if price_data.empty:
        return jsonify({"error": "No data available for the specified stock and period."}), 400
    splits = ticker_obj.splits
    dividends = ticker_obj.dividends

    if price_data.index.tz is not None:
        start_ts = pd.Timestamp(start_date).tz_localize(price_data.index.tz)
        effective_end_ts = pd.Timestamp(effective_end_date).tz_localize(price_data.index.tz)
    else:
        start_ts = pd.Timestamp(start_date)
        effective_end_ts = pd.Timestamp(effective_end_date)

    # Determine investment dates
    if investment_mode == "Lumpsum":
        idx = price_data.index.searchsorted(start_ts, side='left')
        if idx < len(price_data.index):
            investment_dates = [price_data.index[idx]]
        else:
            return jsonify({"error": "No valid trading day found for lumpsum investment."}), 400
    else:
        freq_code = 'MS' if frequency == 'monthly' else 'QS'
        intended_dates = pd.date_range(start=start_ts, end=effective_end_ts, freq=freq_code)
        investment_dates = []
        for intended in intended_dates:
            idx = price_data.index.searchsorted(intended, side='left')
            if idx < len(price_data.index):
                inv_date = price_data.index[idx]
                if inv_date <= effective_end_ts:
                    investment_dates.append(inv_date)
        if not investment_dates:
            return jsonify({"error": "No valid investment dates found in the specified period."}), 400

    app.logger.info("Investment dates: %s", investment_dates)
    
    total_shares = 0
    total_cost = 0.0
    total_dividends = 0.0
    current_investment = investment_value  # For periodic mode, updates annually.
    last_investment_year = None
    report_rows = []  # List of dictionaries for each investment

    for date in price_data.index:
        if date in splits.index:
            total_shares = math.floor(total_shares * splits.loc[date])
        if date in dividends.index:
            total_dividends += total_shares * dividends.loc[date]
        if date in investment_dates:
            if investment_mode == "Periodic":
                if last_investment_year is None or date.year > last_investment_year:
                    if last_investment_year is not None:
                        current_investment *= (1 + yearly_increment)
                    last_investment_year = date.year
            close_price = price_data.loc[date, 'Close']
            if investment_type == 'amount':
                shares_bought = math.floor(current_investment / close_price)
                cost = shares_bought * close_price
            else:
                shares_bought = math.floor(current_investment)
                cost = shares_bought * close_price
            total_shares += shares_bought
            total_cost += cost
            report_rows.append({
                "year": str(date.year),
                "date": date.strftime('%Y-%m-%d'),
                "investment_amount": format_rupee(current_investment),
                "close_price": format_rupee(close_price),
                "shares_bought": str(shares_bought),
                "cost": format_rupee(cost)
            })

    app.logger.info("Report rows: %s", report_rows)

    current_price = price_data['Close'].iloc[-1]
    current_value = total_shares * current_price
    total_return = current_value + total_dividends - total_cost
    percent_return = (total_return / total_cost * 100) if total_cost > 0 else 0

    # Build summary with only desired keys.
    summary = {
        "Total Investments Made": str(len(investment_dates)),
        "Total Amount Invested": format_rupee(total_cost),
        "Total Shares Owned": str(total_shares),
        "Current Value of Shares": format_rupee(current_value),
        "Total Dividends Received": format_rupee(total_dividends),
        "Total Return": format_rupee(total_return),
        "Percentage Return": f"{percent_return:.2f}%"
    }

    app.logger.info("Summary: %s", summary)
    return jsonify({"summary": summary, "report": report_rows})

if __name__ == '__main__':
    app.run(debug=True)



