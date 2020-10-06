# The Defensive Stock Screener is
# a stock screener that allows people
# who are interested in finding valued
# stocks get started in finding
# a list of potential undervalued stocks


import datetime as dt
import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import SimpleQueue, Empty

import finnhub as fh
import pandas as pd
from codetiming import Timer

criteria = {'PE': 10, 'PB': 0.7, 'RG5Y': 10, 'DE': 100, 'CHP': 0.7, 'ROE': 15}
filtered_count = 0


class Stock:
    """A class that stores the information of an undervalued stock"""

    def __init__(self, symbol='', name='', c_price=0, exchange='', industry='', weburl=''):
        self.symbol = symbol
        self.name = name
        self.c_price = c_price
        self.exchange = exchange
        self.industry = industry
        self.web_url = weburl


def read_from_excel() -> pd.DataFrame:
    """
    Read from an excel or csv file that contains the
    a list of stocks in the US.
    """
    while True:
        sym_list = Path(input("Please input a file path that contains the list of stocks you want to filter: "))
        if sym_list.exists() and sym_list.is_file() and sym_list.suffix in ('.csv', '.xlsx', '.xlsm'):
            break
        print("Please try again")
    if sym_list.suffix == '.csv':
        data = pd.read_csv(sym_list)
    else:
        data = pd.read_excel(sym_list)
    return data


def create_api_objects(api_key_file) -> [fh.Client]:
    """Get the API keys from the FinnhubAPIkey.txt
    and create a list ofCLient objects using those keys.
    There are multiple Client objects since an
    API key can only perform 60 calls/minute."""
    api_objects = []
    for key in api_key_file:
        api_objects.append(fh.Client(api_key=key.rstrip()))
    return api_objects


StockQueue = SimpleQueue()
Filtered = SimpleQueue()


def create_global_queue(sc_list: pd.DataFrame) -> None:
    for i in sc_list.columns:
        if i.lower() in ('ticker', 'symbol'):
            ticker = i
            break

    for t in sc_list[ticker]:
        StockQueue.put(t)


def parse_global_queue() -> [Stock]:
    f_list = []

    while True:
        try:
            element = Filtered.get(block=False)
            f_list.append(element)
        except Empty:
            break

    return f_list


def fixed_delay(call, *args: tuple, **kwargs: dict) -> dict:
    start = time.perf_counter() + 1
    if args and kwargs:
        ret = call(*args, **kwargs)
    elif args:
        ret = call(*args)
    elif kwargs:
        ret = call(**kwargs)
    diff = time.perf_counter() - start
    if diff > 0:
        time.sleep(diff)
    return ret


def filter_undervalued_stocks(api: fh.Client) -> None:
    """Find which column contains the tickers of the file and loop through
    that column of the DataFrame object returned from the read_from_excel
    function and perform API calls on each stock."""
    global filtered_count
    while True:
        try:
            t = StockQueue.get(block=False)
        except Empty:
            break
        try:
            data = api.company_basic_financials(symbol=t, metric='all')
        except fh.exceptions.FinnhubAPIException:
            time.sleep(60)
            data = api.company_basic_financials(symbol=t, metric='all')
        stock_metrics = insert_metrics(data)
        if stock_metrics and match_conditions(stock_metrics):
            peak_price = data['metric']['52WeekHigh']
            try:
                last_price = api.quote(symbol=t)['l']
            except fh.exceptions.FinnhubAPIException:
                time.sleep(60)
                last_price = api.quote(symbol=t)['l']
            if (last_price / peak_price) <= criteria['CHP']:
                try:
                    stock_profile = api.company_profile2(symbol=t)
                except fh.exceptions.FinnhubAPIException:
                    time.sleep(60)
                    stock_profile = api.company_profile2(symbol=t)
                valued_stock = Stock(symbol=t)
                valued_stock.c_price = last_price
                if stock_profile:
                    valued_stock.name = stock_profile['name']
                    valued_stock.exchange = stock_profile['exchange']
                    valued_stock.industry = stock_profile['finnhubIndustry']
                    valued_stock.web_url = stock_profile['weburl']
                    Filtered.put(valued_stock)
                    filtered_count += 1
                    logging.info(f"Filtered {filtered_count} stocks. Symbol is {t}")


def insert_metrics(data_dict: dict) -> {str: int}:
    """
    Insert the financial metrics from the API calls
    to a dictionary.
    """
    stock_dict = dict()
    try:
        stock_dict['PE'] = data_dict['metric']['peNormalizedAnnual']
        stock_dict['PB'] = data_dict['metric']['pbAnnual']
        stock_dict['RG5Y'] = data_dict['metric']['revenueGrowth5Y']
        stock_dict['DE'] = data_dict['metric']['totalDebt/totalEquityAnnual']
        stock_dict['ROE'] = data_dict['metric']['roeTTM']
    except KeyError:
        pass
    return stock_dict


def match_conditions(metrics: {str: int}) -> bool:
    """
    Check if all of the financial metrics satisfy
    the requirements of the criteria.
    """
    count = 0
    if type(metrics['PE']) in (int, float) and metrics['PE'] < criteria['PE']:
        count += 1
    if type(metrics['PB']) in (int, float) and metrics['PB'] <= criteria['PB']:
        count += 1
    if type(metrics['RG5Y']) in (int, float) and metrics['RG5Y'] >= criteria['RG5Y']:
        count += 1
    if type(metrics['DE']) in (int, float) and metrics['DE'] < criteria['DE']:
        count += 1
    if type(metrics['ROE']) in (int, float) and metrics['ROE'] >= criteria['ROE']:
        count += 1
    return count >= len(criteria) - 3


def write_to_excel_and_save(location, u_stocks_data: [Stock]) -> None:
    """Write all of the results on an excel file and place
    the file on the path the users provided."""
    excel_data = defaultdict(list)
    current = dt.datetime.now()
    today = f"{current.month}/{current.day}/{current.year}"
    for stocks in u_stocks_data:
        excel_data['Ticker'].append(stocks.symbol)
        excel_data['Name'].append(stocks.name)
        excel_data['Current Price'].append(stocks.c_price)
        excel_data['Exchange'].append(stocks.exchange)
        excel_data['Industry'].append(stocks.industry)
        excel_data["Company's website"].append(stocks.web_url)
        excel_data["Date"].append(today)
    result_df = pd.DataFrame(excel_data)
    result_df.to_excel(location)


def run_program() -> None:
    while True:
        result_location = Path(input("Please select where you want to save your result: "))
        if result_location.exists() and result_location.is_dir():
            break
        print(f"{result_location} is invalid.")
    file_name = input("Please give your result a name (don't include the extension): ")
    t = Timer()
    t.start()
    logging.basicConfig(format='%(asctime)s  %(message)s',
                        datefmt='%y-%m-%d %H:%M:%S', level=logging.INFO)
    stock_list = read_from_excel()
    api_list = create_api_objects(open('FinnhubAPIkey.txt'))

    create_global_queue(stock_list)

    with ThreadPoolExecutor(max_workers=len(api_list)) as executor:
        executor.map(filter_undervalued_stocks, api_list)

    f_list = parse_global_queue()

    c_time = dt.datetime.now()
    file_name += f'_{c_time.hour}_{c_time.minute}_{c_time.second}'
    destination = result_location / f"{file_name}.xlsx"
    write_to_excel_and_save(destination, f_list)
    print(f"Filtering is done. Please check {result_location}.")
    t.stop()


if __name__ == "__main__":
    run_program()