import datetime as dt
import urllib
from os import PathLike
from typing import Union
from pathlib import Path

import pandas as pd
from dateutil.relativedelta import relativedelta

from econuy.resources import columns
from econuy.resources.lstrings import (reserves_cols, reserves_url,
                                       missing_reserves_url)


def get(update: Union[str, PathLike, None] = None,
        save: Union[str, PathLike, None] = None,
        name: Union[str, None] = None):
    """Get international reserves change data from online sources.

    Use as input a list of strings of the format %b%Y, each representing a
    month of data.

    Parameters
    ----------
    update : str, PathLike or bool (default is False)
        Path, path-like string pointing to a CSV file for updating, or bool,
        in which case if True, save in predefined file, or False, don't update.
    save : str, PathLike or bool (default is False)
        Path, path-like string pointing to a CSV file for saving, or bool,
        in which case if True, save in predefined file, or False, don't save.

    Returns
    -------
    reserves : Pandas dataframe

    """
    if name is None:
        name = "reserves_chg"
    months = ["ene", "feb", "mar", "abr", "may", "jun",
              "jul", "ago", "set", "oct", "nov", "dic"]
    years = list(range(2013, dt.datetime.now().year + 1))
    files = [month + str(year) for year in years for month in months]

    urls = [f"{reserves_url}{file}.xls" for file in files]
    wrong_may14 = f"{reserves_url}may2014.xls"
    fixed_may14 = f"{reserves_url}mayo2014.xls"
    urls = [fixed_may14 if x == wrong_may14 else x for x in urls]

    if update is not None:
        update_path = (Path(update) / name).with_suffix(".csv")
        try:
            previous_data = pd.read_csv(update_path, index_col=0,
                                        header=list(range(9)))
            previous_data.columns = reserves_cols[1:46]
            previous_data.index = pd.to_datetime(previous_data.index)
            urls = urls[-18:]
        except FileNotFoundError:
            previous_data = pd.DataFrame()
            pass

    reports = []
    for url in urls:

        try:
            with pd.ExcelFile(url) as xls:
                month_of_report = pd.read_excel(xls, sheet_name="INDICE")
                raw = pd.read_excel(xls, sheet_name="ACTIVOS DE RESERVA",
                                    skiprows=3)
            first_day = month_of_report.iloc[7, 4]
            last_day = (first_day
                        + relativedelta(months=1)
                        - dt.timedelta(days=1))
            proc = raw.dropna(axis=0, thresh=20).dropna(axis=1, thresh=20)
            proc = proc.transpose()
            proc.index.name = "Date"
            proc = proc.iloc[:, 1:46]
            proc.columns = reserves_cols[1:46]
            proc = proc.iloc[1:]
            proc.index = pd.to_datetime(proc.index, errors="coerce")
            proc = proc.loc[proc.index.dropna()]
            proc = proc.loc[first_day:last_day]
            reports.append(proc)

        except urllib.error.HTTPError:
            print(f"{url} could not be reached.")
            pass

    mar14 = pd.read_excel(missing_reserves_url, index_col=0)
    mar14.columns = reserves_cols[1:46]
    reserves = pd.concat(reports + [mar14], sort=False).sort_index()

    if update is not None:
        reserves = previous_data.append(reserves, sort=False)
        reserves = reserves.loc[~reserves.index.duplicated(keep="last")]

    reserves = reserves.apply(pd.to_numeric, errors="coerce")
    columns._setmeta(reserves, area="Reservas internacionales",
                     currency="USD", inf_adj="No", index="No",
                     seas_adj="NSA", ts_type="Flujo", cumperiods=1)

    if save is not None:
        save_path = (Path(save) / name).with_suffix(".csv")
        reserves.to_csv(save_path)

    return reserves
