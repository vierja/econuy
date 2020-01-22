import os
import datetime as dt
import zipfile
import tempfile
from io import BytesIO

import pandas as pd
import numpy as np
from pandas.tseries.offsets import YearEnd, MonthEnd
import requests

from config import ROOT_DIR
from processing import updates
from processing.utils import (BEEF_URL, PULP_URL, SOYBEAN_URL,
                              WHEAT_URL, IMF_URL, MILK1_URL, MILK2_URL)

DATA_PATH = os.path.join(ROOT_DIR, "data")
WEIGHTS_PATH = os.path.join(DATA_PATH, "other",
                            "commodity_exports_wits.csv")
BUSHEL_CONV = 36.74 / 100
UPDATE_THRESHOLD = 10


def weights(window=3):

    raw = pd.read_csv(WEIGHTS_PATH)
    table = raw.pivot(index="Year", columns="ProductDescription",
                      values="TradeValue in 1000 USD")
    table.fillna(0, inplace=True)
    not_considered = ["Maize except sweet corn.", "Wine of fresh grapes",
                      "Hide/skin/fur, raw", "Sugar/sugar prep/honey",
                      "Fish/shellfish/etc.", "Vegetables and fruit",
                      "Malt/ malt flour"]
    table.drop(not_considered, axis=1, inplace=True)
    percentage = table.div(table.sum(axis=1), axis=0)
    percentage.index = (pd.to_datetime(percentage.index, format="%Y")
                        + YearEnd(1))
    rolling = percentage.rolling(window=window, min_periods=window).mean()
    resampled_weights = rolling.resample("M").bfill()

    beef = ["Beef offal, frozen", "Beef offal,fresh/chilled",
            "Beef prepared/presvd nes", "Beef, fresh/chilld/frozn",
            "Bovine animals, live"]
    resampled_weights["Beef"] = resampled_weights[beef].sum(
        axis=1, min_count=len(beef)
    )
    resampled_weights.drop(beef, axis=1, inplace=True)
    resampled_weights.columns = ["Barley", "Wood", "Gold", "Milk", "Pulp",
                                 "Rice", "Soybeans", "Wheat", "Wool", "Beef"]

    return resampled_weights


def prices(update=None, revise_rows=0, save=None, force_update=False):

    if update is not None:
        update_path = os.path.join(DATA_PATH, update)
        modified_time = dt.datetime.fromtimestamp(os.path.getmtime(update_path))
        delta = (dt.datetime.now() - modified_time).days
        previous_data = pd.read_csv(update_path, sep=" ", index_col=0)
        previous_data.index = pd.to_datetime(previous_data.index)

        if delta < UPDATE_THRESHOLD and force_update is False:
            print(f"{update} was modified within {UPDATE_THRESHOLD} day(s). "
                  f"Skipping download...")
            return previous_data

    raw_beef = (pd.read_excel(BEEF_URL, header=4, index_col=0)
                .dropna(how="all").drop(index=0))
    raw_beef.columns = raw_beef.columns.str.strip()
    proc_beef = raw_beef["Ing. Prom./Ton."].to_frame()
    proc_beef.index = pd.date_range(start="2002-01-04",
                                    periods=len(proc_beef), freq="W-SAT")
    proc_beef["Ing. Prom./Ton."] = np.where(
        proc_beef > np.mean(proc_beef) + np.std(proc_beef) * 2,
        proc_beef / 1000,
        proc_beef,
    )
    beef = proc_beef.resample("M").mean()

    raw_pulp_r = requests.get(PULP_URL)
    temp_dir = tempfile.TemporaryDirectory()
    with zipfile.ZipFile(BytesIO(raw_pulp_r.content), "r") as f:
        f.extractall(path=temp_dir.name)
        path = os.path.join(temp_dir.name, "monthly_values.csv")
        raw_pulp = pd.read_csv(path, sep=";").dropna(how="any")
    proc_pulp = raw_pulp.copy().sort_index(ascending=False)
    proc_pulp.index = pd.date_range(start="1990-01-31",
                                    periods=len(proc_pulp), freq="M")
    proc_pulp.drop(["Label", "Codes"], axis=1, inplace=True)
    pulp = proc_pulp

    soy_wheat = []
    for url in [SOYBEAN_URL, WHEAT_URL]:
        raw = pd.read_csv(url, index_col=0)
        proc = (raw["Settle"] * BUSHEL_CONV).to_frame()
        proc.index = pd.to_datetime(proc.index, format="%Y-%m-%d")
        proc.sort_index(inplace=True)
        soy_wheat.append(proc.resample("M").mean())
    soybean = soy_wheat[0]
    wheat = soy_wheat[1]

    milk = []
    for region, row in {MILK1_URL: 14, MILK2_URL: 13}.items():
        raw_milk = pd.read_excel(region, skiprows=row,
                                 nrows=dt.datetime.now().year - 2007)
        raw_milk.dropna(how="all", axis=1, inplace=True)
        raw_milk.drop(["Promedio ", "Variación"], axis=1, inplace=True)
        raw_milk.columns = ["Año/Mes"] + list(range(1, 13))
        proc_milk = pd.melt(raw_milk, id_vars=["Año/Mes"])
        proc_milk.sort_values(by=["Año/Mes", "variable"], inplace=True)
        proc_milk.index = pd.date_range(start="2007-01-31",
                                        periods=len(proc_milk), freq="M")
        milk.append(proc_milk.iloc[:, 2].to_frame())
    milk = pd.concat(milk, axis=1).mean(axis=1).to_frame()
    milk.columns = ["Price"]
    prev_milk = pd.read_csv(os.path.join(DATA_PATH, "other",
                                         "milk_oceania_europe_fao.csv"),
                            index_col=0)
    prev_milk.index = pd.to_datetime(prev_milk.index,
                                     format="%b-%y") + MonthEnd(1)
    prev_milk = prev_milk.replace(",", "", regex=True)
    prev_milk = pd.to_numeric(prev_milk.squeeze()).to_frame()
    prev_milk = prev_milk.loc[prev_milk.index < min(milk.index)]
    prev_milk.columns = ["Price"]
    milk = prev_milk.append(milk)

    raw_imf = pd.read_excel(IMF_URL)
    raw_imf.columns = raw_imf.iloc[0, :]
    proc_imf = raw_imf.iloc[3:, 1:]
    proc_imf.index = pd.date_range(start="1980-01-31",
                                   periods=len(proc_imf), freq="M")

    rice = proc_imf[proc_imf.columns[proc_imf.columns.str.contains("Rice")]]
    wood = proc_imf[proc_imf.columns[
        proc_imf.columns.str.contains("Sawnwood")
    ]]
    wood = wood.mean(axis=1).to_frame()
    wool = proc_imf[proc_imf.columns[proc_imf.columns.str.startswith("Wool")]]
    wool = wool.mean(axis=1).to_frame()
    barley = proc_imf[proc_imf.columns[
        proc_imf.columns.str.startswith("Barley")
    ]]
    gold = proc_imf[proc_imf.columns[
        proc_imf.columns.str.startswith("Gold")
    ]]

    complete = pd.concat([beef, pulp, soybean, milk, rice, wood, wool, barley,
                          gold, wheat], axis=1)
    complete = complete.reindex(beef.index).dropna(thresh=9)
    complete.columns = ["Beef", "Pulp", "Soybeans", "Milk", "Rice", "Wood",
                        "Wool", "Barley", "Gold", "Wheat"]

    if update is not None:
        complete = updates.revise(new_data=complete, prev_data=previous_data,
                                  revise_rows=revise_rows)

    if save is not None:
        save_path = os.path.join(DATA_PATH, save)
        complete.to_csv(save_path, sep=" ")

    return complete


def get(save=None):

    _prices = prices(update="commodity_prices.csv", revise_rows=3,
                     save="commodity_prices.csv", force_update=False)
    _prices = _prices.interpolate(method="linear", limit=1).dropna(how="any")
    _prices = _prices.pct_change(periods=1)
    _weights = weights(window=3)
    _weights = _weights[_prices.columns]
    _weights = _weights.reindex(_prices.index, method="ffill")

    product = pd.DataFrame(_prices.values * _weights.values,
                           columns=_prices.columns, index=_prices.index)
    product = product.sum(axis=1).add(1).to_frame().cumprod()

    if save is not None:
        save_path = os.path.join(DATA_PATH, save)
        product.to_csv(save_path, sep=" ")

    return product


