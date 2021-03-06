import warnings
from datetime import date
from os import PathLike
from typing import Union, Optional
from urllib.error import HTTPError, URLError

import pandas as pd
import numpy as np
from opnieuw import retry
from scipy.stats.mstats_basic import winsorize
from scipy.stats import stats
from sqlalchemy.engine.base import Connection, Engine

from econuy import transform
from econuy.retrieval import nxr, cpi, fiscal_accounts, labor, trade
from econuy.utils import metadata, ops
from econuy.utils.lstrings import fiscal_metadata, urls, prod_details


def fiscal(aggregation: str = "gps", fss: bool = True,
           unit: Optional[str] = None,
           start_date: Union[str, date, None] = None,
           end_date: Union[str, date, None] = None,
           update_loc: Union[str, PathLike, Engine,
                             Connection, None] = None,
           save_loc: Union[str, PathLike, Engine,
                           Connection, None] = None,
           only_get: bool = True,
           name: str = "tfm_fiscal",
           index_label: str = "index") -> pd.DataFrame:
    """
    Get fiscal accounts data.

    Allow choosing government aggregation, whether to exclude the FSS
    (Fideicomiso  de la Seguridad Social, Social Security Trust Fund), the unit
    (UYU, real UYU, USD, real USD or percent of GDP), periods to accumuldate
    for rolling sums and seasonal adjustment.

    Parameters
    ----------
    aggregation : {'gps', 'nfps', 'gc'}
        Government aggregation. Can be ``gps`` (consolidated public sector),
        ``nfps`` (non-financial public sector) or ``gc`` (central government).
    fss : bool, default True
        If ``True``, exclude the `FSS's <https://www.impo.com.uy/bases/decretos
        /71-2018/25>`_ income from gov't revenues and the FSS's
        interest revenues from gov't interest payments.
    unit : {None, 'gdp', 'usd', 'real', 'real_usd'}
        Unit in which data should be expressed. Possible values are ``real``,
        ``usd``, ``real_usd`` and ``gdp``. If ``None`` or another string is
        set, no unit calculations will be performed, rendering the data as is
        (current UYU).
    start_date : str, datetime.date or None, default None
        If ``unit`` is set to ``real`` or ``real_usd``, this parameter and
        ``end_date`` control how deflation is calculated.
    end_date :
        If ``unit`` is set to ``real`` or ``real_usd``, this parameter and
        ``start_date`` control how deflation is calculated.
    update_loc : str, os.PathLike, SQLAlchemy Connection or Engine, or None, \
                  default None
        Either Path or path-like string pointing to a directory where to find
        a CSV for updating, SQLAlchemy connection or engine object, or
        ``None``, don't update.
    save_loc : str, os.PathLike, SQLAlchemy Connection or Engine, or None, \
                default None
        Either Path or path-like string pointing to a directory where to save
        the CSV, SQL Alchemy connection or engine object, or ``None``,
        don't save.
    name : str, default 'tfm_fiscal'
        Either CSV filename for updating and/or saving, or table name if
        using SQL. Options will be appended to the base name.
    index_label : str, default 'index'
        Label for SQL indexes.
    only_get : bool, default True
        If True, don't download data, retrieve what is available from
        ``update_loc`` for the commodity index.

    Returns
    -------
    Fiscal aggregation : pd.DataFrame

    Raises
    ------
    ValueError
        If ``seas_adj``, ``unit`` or ``aggregation`` are given an invalid
        keywords.

    """
    if unit not in ["gdp", "usd", "real", "real_usd", None]:
        raise ValueError("'unit' can be 'gdp', 'usd', 'real', 'real_usd' or"
                         " None.")
    if aggregation not in ["gps", "nfps", "gc"]:
        raise ValueError("'aggregation' can be 'gps', 'nfps' or 'gc'.")

    if unit is None:
        unit = "uyu"
    name = f"{name}_{aggregation}_{unit}"
    if fss:
        name = name + "_fssadj"

    data = fiscal_accounts.get(update_loc=update_loc,
                               save_loc=save_loc, only_get=only_get)
    gps = data["gps"]
    nfps = data["nfps"]
    gc = data["gc-bps"]

    proc = pd.DataFrame(index=gps.index)
    proc["Ingresos: SPNF-SPC"] = nfps["Ingresos: SPNF"]
    proc["Ingresos: GC-BPS"] = gc["Ingresos: GC-BPS"]
    proc["Egresos: Primarios SPNF-SPC"] = nfps["Egresos: Primarios SPNF"]
    proc["Egresos: Totales GC-BPS"] = gc["Egresos: GC-BPS"]
    proc["Egresos: Inversiones SPNF-SPC"] = nfps["Egresos: Inversiones"]
    proc["Egresos: Inversiones GC-BPS"] = gc["Egresos: Inversión"]
    proc["Intereses: SPNF"] = nfps["Intereses: Totales"]
    proc["Intereses: BCU"] = gps["Intereses: BCU"]
    proc["Intereses: SPC"] = proc["Intereses: SPNF"] + proc["Intereses: BCU"]
    proc["Intereses: GC-BPS"] = gc["Intereses: Total"]
    proc["Egresos: Totales SPNF"] = (proc["Egresos: Primarios SPNF-SPC"]
                                     + proc["Intereses: SPNF"])
    proc["Egresos: Totales SPC"] = (proc["Egresos: Totales SPNF"]
                                    + proc["Intereses: BCU"])
    proc["Egresos: Primarios GC-BPS"] = (proc["Egresos: Totales GC-BPS"]
                                         - proc["Intereses: GC-BPS"])
    proc["Resultado: Primario intendencias"] = nfps[
        "Resultado: Primario intendencias"
    ]
    proc["Resultado: Primario BSE"] = nfps["Resultado: Primario BSE"]
    proc["Resultado: Primario BCU"] = gps["Resultado: Primario BCU"]
    proc["Resultado: Primario SPNF"] = nfps["Resultado: Primario SPNF"]
    proc["Resultado: Global SPNF"] = nfps["Resultado: Global SPNF"]
    proc["Resultado: Primario SPC"] = gps["Resultado: Primario SPC"]
    proc["Resultado: Global SPC"] = gps["Resultado: Global SPC"]
    proc["Resultado: Primario GC-BPS"] = (proc["Ingresos: GC-BPS"]
                                          - proc["Egresos: Primarios GC-BPS"])
    proc["Resultado: Global GC-BPS"] = gc["Resultado: Global GC-BPS"]

    proc["Ingresos: FSS"] = gc["Ingresos: FSS"]
    proc["Intereses: FSS"] = gc["Intereses: BPS-FSS"]
    proc["Ingresos: SPNF-SPC aj. FSS"] = (proc["Ingresos: SPNF-SPC"]
                                          - proc["Ingresos: FSS"])
    proc["Ingresos: GC-BPS aj. FSS"] = (proc["Ingresos: GC-BPS"]
                                        - proc["Ingresos: FSS"])
    proc["Intereses: SPNF aj. FSS"] = (proc["Intereses: SPNF"]
                                       - proc["Intereses: FSS"])
    proc["Intereses: SPC aj. FSS"] = (proc["Intereses: SPC"]
                                      - proc["Intereses: FSS"])
    proc["Intereses: GC-BPS aj. FSS"] = (proc["Intereses: GC-BPS"]
                                         - proc["Intereses: FSS"])
    proc["Egresos: Totales SPNF aj. FSS"] = (proc["Egresos: Totales SPNF"]
                                             - proc["Intereses: FSS"])
    proc["Egresos: Totales SPC aj. FSS"] = (proc["Egresos: Totales SPC"]
                                            - proc["Intereses: FSS"])
    proc["Egresos: Totales GC-BPS aj. FSS"] = (proc["Egresos: Totales GC-BPS"]
                                               - proc["Intereses: FSS"])
    proc["Resultado: Primario SPNF aj. FSS"] = (
        proc["Resultado: Primario SPNF"]
        - proc["Ingresos: FSS"])
    proc["Resultado: Global SPNF aj. FSS"] = (proc["Resultado: Global SPNF"]
                                              - proc["Ingresos: FSS"]
                                              + proc["Intereses: FSS"])
    proc["Resultado: Primario SPC aj. FSS"] = (proc["Resultado: Primario SPC"]
                                               - proc["Ingresos: FSS"])
    proc["Resultado: Global SPC aj. FSS"] = (proc["Resultado: Global SPC"]
                                             - proc["Ingresos: FSS"]
                                             + proc["Intereses: FSS"])
    proc["Resultado: Primario GC-BPS aj. FSS"] = (
        proc["Resultado: Primario GC-BPS"]
        - proc["Ingresos: FSS"])
    proc["Resultado: Global GC-BPS aj. FSS"] = (
        proc["Resultado: Global GC-BPS"]
        - proc["Ingresos: FSS"]
        + proc["Intereses: FSS"])

    output = proc.loc[:, fiscal_metadata[aggregation][fss]]
    metadata._set(output, area="Cuentas fiscales y deuda",
                  currency="UYU", inf_adj="No", unit="Millones",
                  seas_adj="NSA", ts_type="Flujo", cumperiods=1)

    if unit == "gdp":
        output = transform.rolling(output, periods=12, operation="sum")
        output = transform.convert_gdp(output, update_loc=update_loc,
                                       save_loc=save_loc,
                                       only_get=only_get)
    elif unit == "usd":
        output = transform.convert_usd(output, update_loc=update_loc,
                                       save_loc=save_loc,
                                       only_get=only_get)
    elif unit == "real_usd":
        output = transform.convert_real(output, start_date=start_date,
                                        end_date=end_date,
                                        update_loc=update_loc,
                                        save_loc=save_loc,
                                        only_get=only_get)
        xr = nxr.get_monthly(update_loc=update_loc,
                             save_loc=save_loc,
                             only_get=only_get)
        output = output.divide(xr[start_date:end_date].mean()[1])
        metadata._set(output, currency="USD")
    elif unit == "real":
        output = transform.convert_real(output, start_date=start_date,
                                        end_date=end_date,
                                        update_loc=update_loc,
                                        save_loc=save_loc,
                                        only_get=only_get)

    if save_loc is not None:
        ops._io(operation="save", data_loc=save_loc,
                data=output, name=name, index_label=index_label)

    return output


@retry(
    retry_on_exceptions=(HTTPError, URLError),
    max_calls_total=4,
    retry_window_after_first_call_in_seconds=60,
)
def labor_rate_people(seas_adj: Union[str, None] = None,
                      update_loc: Union[str, PathLike, Engine,
                                        Connection, None] = None,
                      save_loc: Union[str, PathLike, Engine,
                                      Connection, None] = None,
                      name: str = "tfm_labor",
                      index_label: str = "index",
                      only_get: bool = True) -> pd.DataFrame:
    """
    Get labor data, both rates and persons. Allow choosing seasonal adjustment.

    Parameters
    ----------
    seas_adj : {None, 'trend', 'seas'}
        Whether to seasonally adjust.
    update_loc : str, os.PathLike, SQLAlchemy Connection or Engine, or None, \
                  default None
        Either Path or path-like string pointing to a directory where to find
        a CSV for updating, SQLAlchemy connection or engine object, or
        ``None``, don't update.
    save_loc : str, os.PathLike, SQLAlchemy Connection or Engine, or None, \
                default None
        Either Path or path-like string pointing to a directory where to save
        the CSV, SQL Alchemy connection or engine object, or ``None``,
        don't save.
    name : str, default 'tfm_labor'
        Either CSV filename for updating and/or saving, or table name if
        using SQL.
    index_label : str, default 'index'
        Label for SQL indexes.
    only_get : bool, default True
        If True, don't download data, retrieve what is available from
        ``update_loc`` for the commodity index.

    Returns
    -------
    Labor market data : pd.DataFrame

    Raises
    ------
    ValueError
        If ``seas_adj`` is given an invalid keyword.

    """
    if seas_adj not in ["trend", "seas", None]:
        raise ValueError("'seas_adj' can be 'trend', 'seas' or None.")

    rates = labor.get_rates(update_loc=update_loc, only_get=only_get)
    rates = rates.loc[:, ["Tasa de actividad: total", "Tasa de empleo: total",
                          "Tasa de desempleo: total"]]
    rates.columns.set_levels(rates.columns.levels[0].str.replace(": total",
                                                                 ""),
                             level=0, inplace=True)

    if seas_adj in ["trend", "seas"]:
        trend, seasadj = transform.decompose(rates, trading=True, outlier=True)
        if seas_adj == "trend":
            rates = trend
        elif seas_adj == "seas":
            rates = seasadj

    working_age = pd.read_excel(urls["tfm_labor"]["dl"]["population"],
                                skiprows=7, index_col=0,
                                nrows=92).dropna(how="all")
    ages = list(range(14, 90)) + ["90 y más"]
    working_age = working_age.loc[ages].sum()
    working_age.index = pd.date_range(start="1996-06-30", end="2050-06-30",
                                      freq="A-JUN")
    monthly_working_age = working_age.resample("M").interpolate("linear")
    monthly_working_age = monthly_working_age.loc[rates.index]
    persons = rates.iloc[:, [0, 1]].div(100).mul(monthly_working_age, axis=0)
    persons["Desempleados"] = rates.iloc[:, 2].div(100).mul(persons.iloc[:, 0])
    persons.columns = ["Activos", "Empleados", "Desempleados"]
    seas_text = "NSA"
    if seas_adj == "trend":
        seas_text = "Trend"
    elif seas_adj == "seas":
        seas_text = "SA"
    metadata._set(persons, area="Mercado laboral", currency="-",
                  inf_adj="No", unit="Personas", seas_adj=seas_text,
                  ts_type="-", cumperiods=1)

    output = pd.concat([rates, persons], axis=1)

    name = f"{name}_{seas_text.lower()}"

    if save_loc is not None:
        ops._io(operation="save", data_loc=save_loc,
                data=output, name=name, index_label=index_label)

    return output


def labor_real_wages(seas_adj: Union[str, None] = None,
                     update_loc: Union[str, PathLike, Engine,
                                       Connection, None] = None,
                     save_loc: Union[str, PathLike, Engine,
                                     Connection, None] = None,
                     name: str = "tfm_wages",
                     index_label: str = "index",
                     only_get: bool = True) -> pd.DataFrame:
    """
    Get real wages. Allow choosing seasonal adjustment.

    Parameters
    ----------
    seas_adj : {'trend', 'seas', None}
        Whether to seasonally adjust.
    update_loc : str, os.PathLike, SQLAlchemy Connection or Engine, or None, \
                  default None
        Either Path or path-like string pointing to a directory where to find
        a CSV for updating, SQLAlchemy connection or engine object, or
        ``None``, don't update.
    save_loc : str, os.PathLike, SQLAlchemy Connection or Engine, or None, \
                default None
        Either Path or path-like string pointing to a directory where to save
        the CSV, SQL Alchemy connection or engine object, or ``None``,
        don't save.
    name : str, default 'tfm_wages'
        Either CSV filename for updating and/or saving, or table name if
        using SQL.
    index_label : str, default 'index'
        Label for SQL indexes.
    only_get : bool, default True
        If True, don't download data, retrieve what is available from
        ``update_loc`` for the commodity index.

    Returns
    -------
    Real wages data : pd.DataFrame

    Raises
    ------
    ValueError
        If ``seas_adj`` is given an invalid keyword.

    """
    if seas_adj not in ["trend", "seas", None]:
        raise ValueError("'seas_adj' can be 'trend', 'seas' or None.")

    wages = labor.get_wages(update_loc=update_loc, only_get=only_get)
    real_wages = wages.copy()
    real_wages.columns = ["Índice medio de salarios reales",
                          "Índice medio de salarios reales privados",
                          "Índice medio de salarios reales públicos"]
    metadata._set(real_wages, area="Mercado laboral", currency="UYU",
                  inf_adj="Sí", seas_adj="NSA", ts_type="-", cumperiods=1)
    real_wages = transform.convert_real(real_wages, update_loc=update_loc,
                                        only_get=only_get)
    output = pd.concat([wages, real_wages], axis=1)
    seas_text = "nsa"
    if seas_adj in ["trend", "seas"]:
        trend, seasadj = transform.decompose(output,
                                             trading=True, outlier=False)
        if seas_adj == "trend":
            output = trend
            seas_text = "trend"
        elif seas_adj == "seas":
            output = seasadj
            seas_text = "sa"

    output = transform.base_index(output, start_date="2008-07-31")

    name = f"{name}_{seas_text}"

    if save_loc is not None:
        ops._io(operation="save", data_loc=save_loc,
                data=output, name=name, index_label=index_label)

    return output


def trade_balance(update_loc: Union[str, PathLike, Engine,
                                    Connection, None] = None,
                  save_loc: Union[str, PathLike, Engine,
                                  Connection, None] = None,
                  name: str = "tfm_tb",
                  index_label: str = "index",
                  only_get: bool = True) -> pd.DataFrame:
    """
    Get trade balance values by country/region.

    Parameters
    ----------
    update_loc : str, os.PathLike, SQLAlchemy Connection or Engine, or None, \
                  default None
        Either Path or path-like string pointing to a directory where to find
        a CSV for updating, SQLAlchemy connection or engine object, or
        ``None``, don't update.
    save_loc : str, os.PathLike, SQLAlchemy Connection or Engine, or None, \
                default None
        Either Path or path-like string pointing to a directory where to save
        the CSV, SQL Alchemy connection or engine object, or ``None``,
        don't save.
    name : str, default 'tfm_tb'
        Either CSV filename for updating and/or saving, or table name if
        using SQL.
    index_label : str, default 'index'
        Label for SQL indexes.
    only_get : bool, default True
        If True, don't download data, retrieve what is available from
        ``update_loc`` for the commodity index.

    Returns
    -------
    Net trade balance value by region/country : pd.DataFrame

    """
    data = trade.get(update_loc=update_loc, save_loc=save_loc,
                     only_get=only_get)
    exports = data["tb_x_dest_val"].rename(
        columns={"Total exportaciones": "Total"}
    )
    imports = data["tb_m_orig_val"].rename(
        columns={"Total importaciones": "Total"}
    )
    net = exports - imports

    if save_loc is not None:
        ops._io(operation="save", data_loc=save_loc,
                data=net, name=name, index_label=index_label)

    return net


def terms_of_trade(update_loc: Union[str, PathLike, Engine,
                                     Connection, None] = None,
                   save_loc: Union[str, PathLike, Engine,
                                   Connection, None] = None,
                   name: str = "tfm_tot",
                   index_label: str = "index",
                   only_get: bool = True) -> pd.DataFrame:
    """
    Get terms of trade.

    Parameters
    ----------
    update_loc : str, os.PathLike, SQLAlchemy Connection or Engine, or None, \
                  default None
        Either Path or path-like string pointing to a directory where to find
        a CSV for updating, SQLAlchemy connection or engine object, or
        ``None``, don't update.
    save_loc : str, os.PathLike, SQLAlchemy Connection or Engine, or None, \
                default None
        Either Path or path-like string pointing to a directory where to save
        the CSV, SQL Alchemy connection or engine object, or ``None``,
        don't save.
    name : str, default 'tfm_tot'
        Either CSV filename for updating and/or saving, or table name if
        using SQL.
    index_label : str, default 'index'
        Label for SQL indexes.
    only_get : bool, default True
        If True, don't download data, retrieve what is available from
        ``update_loc`` for the commodity index.

    Returns
    -------
    Terms of trade (exports/imports) : pd.DataFrame

    """
    data = trade.get(update_loc=update_loc, save_loc=save_loc,
                     only_get=only_get)
    exports = data["tb_x_dest_pri"].rename(
        columns={"Total exportaciones": "Total"}
    )
    imports = data["tb_m_orig_pri"].rename(
        columns={"Total importaciones": "Total"}
    )
    tot = exports / imports
    tot = tot.loc[:, ["Total"]]
    tot.rename(columns={"Total": "Términos de intercambio"}, inplace=True)
    tot = transform.base_index(tot, start_date="2005-01-01",
                               end_date="2005-12-31")
    metadata._set(tot, ts_type="-")

    if save_loc is not None:
        ops._io(operation="save", data_loc=save_loc,
                data=tot, name=name, index_label=index_label)

    return tot


@retry(
    retry_on_exceptions=(HTTPError, URLError),
    max_calls_total=4,
    retry_window_after_first_call_in_seconds=60,
)
def cpi_measures(update_loc: Union[str, PathLike,
                                   Engine, Connection, None] = None,
                 revise_rows: Union[str, int] = "nodup",
                 save_loc: Union[str, PathLike, Engine,
                                 Connection, None] = None,
                 name: str = "tfm_prices", index_label: str = "index",
                 only_get: bool = False) -> pd.DataFrame:
    """Get core CPI, Winsorized CPI, tradabe CPI and non-tradable CPI.

    Parameters
    ----------
    update_loc : str, os.PathLike, SQLAlchemy Connection or Engine, or None, \
                  default None
        Either Path or path-like string pointing to a directory where to find
        a CSV for updating, SQLAlchemy connection or engine object, or
        ``None``, don't update.
    revise_rows : {'nodup', 'auto', int}
        Defines how to process data updates. An integer indicates how many rows
        to remove from the tail of the dataframe and replace with new data.
        String can either be ``auto``, which automatically determines number of
        rows to replace from the inferred data frequency, or ``nodup``,
        which replaces existing periods with new data.
    save_loc : str, os.PathLike, SQLAlchemy Connection or Engine, or None, \
                default None
        Either Path or path-like string pointing to a directory where to save
        the CSV, SQL Alchemy connection or engine object, or ``None``,
        don't save.
    name : str, default 'tfm_prices'
        Either CSV filename for updating and/or saving, or table name if
        using SQL.
    index_label : str, default 'index'
        Label for SQL indexes.
    only_get : bool, default False
        If True, don't download data, retrieve what is available from
        ``update_loc``.

    Returns
    -------
    Monthly CPI measures : pd.DataFrame

    """
    if only_get is True and update_loc is not None:
        output = ops._io(operation="update", data_loc=update_loc,
                         name=name, index_label=index_label)
        if not output.equals(pd.DataFrame()):
            return output

    xls = pd.ExcelFile(urls["tfm_prices"]["dl"]["main"])
    weights = pd.read_excel(xls, sheet_name=xls.sheet_names[0],
                            usecols="A:C", skiprows=14,
                            index_col=0).dropna(how="any")
    weights.columns = ["Item", "Weight"]
    weights_8 = weights.loc[weights.index.str.len() == 8]
    sheets = []
    for sheet in xls.sheet_names:
        raw = pd.read_excel(xls, sheet_name=sheet, usecols="D:IN",
                            skiprows=9).dropna(how="all")
        proc = raw.loc[:, raw.columns.str.
                              contains("Indice|Índice")].dropna(how="all")
        sheets.append(proc.T)
    output = pd.concat(sheets)
    output = output.iloc[:, 1:]
    output.columns = [weights["Item"], weights.index]
    output.index = pd.date_range(start="2010-12-31", periods=len(output),
                                 freq="M")
    diff_8 = output.loc[:, output.columns.get_level_values(level=1).str.len()
                           == 8].pct_change()
    win = pd.DataFrame(winsorize(diff_8, limits=(0.05, 0.05), axis=1))
    win.index = diff_8.index
    win.columns = diff_8.columns.get_level_values(level=1)
    cpi_win = win.mul(weights_8.loc[:, "Weight"].T)
    cpi_win = cpi_win.sum(axis=1).add(1).cumprod().mul(100)

    prod_97 = (pd.read_excel(urls["tfm_prices"]["dl"]["historical"],
                             skiprows=5).dropna(how="any")
               .set_index("Rubros, Agrupaciones y Subrubros").T)
    prod_97 = prod_97.loc[:, prod_details[1]].pct_change()
    output_8 = output.loc[:, prod_details[0]].pct_change()
    output_8 = output_8.loc[:, ~output_8.columns.get_level_values(level=0)
        .duplicated()]
    output_8.columns = output_8.columns.get_level_values(level=0)
    prod_97.columns = output_8.columns.get_level_values(level=0)
    complete = pd.concat([prod_97, output_8.iloc[1:]])
    complete.index = pd.date_range(start="1997-03-31", freq="M",
                                   periods=len(complete))
    weights_complete = weights.loc[weights["Item"].isin(complete.columns)]
    weights_complete = weights_complete.loc[~weights_complete["Item"]
        .duplicated()].set_index("Item")
    tradable = complete.loc[:, [bool(x) for x in prod_details[2]]]
    tradable_weights = weights_complete.loc[
        weights_complete.index.isin(tradable.columns), "Weight"
    ].T
    tradable_weights = tradable_weights.div(tradable_weights.sum())
    tradable = (tradable.mul(tradable_weights).sum(axis=1)
                .add(1).cumprod().mul(100))

    non_tradable = complete.loc[:, [not bool(x) for x in prod_details[2]]]
    non_tradable_weights = weights_complete.loc[
        weights_complete.index.isin(non_tradable.columns), "Weight"
    ].T
    non_tradable_weights = non_tradable_weights.div(non_tradable_weights.sum())
    non_tradable = (non_tradable.mul(non_tradable_weights)
                    .sum(axis=1).add(1).cumprod().mul(100))

    core = complete.loc[:, [bool(x) for x in prod_details[3]]]
    core_weights = weights_complete.loc[
        weights_complete.index.isin(core.columns), "Weight"
    ].T
    core_weights = core_weights.div(core_weights.sum())
    core = (core.mul(core_weights)
            .sum(axis=1).add(1).cumprod().mul(100))

    cpi_re = cpi.get(update_loc=update_loc, save_loc=save_loc, only_get=True)
    cpi_re = cpi_re.loc[cpi_re.index >= "1997-03-31"]
    output = pd.concat([cpi_re, tradable, non_tradable, core, cpi_win], axis=1)
    output = transform.base_index(output, start_date="2010-12-01",
                                  end_date="2010-12-31")
    output.columns = ["Índice de precios al consumo: total",
                      "Índice de precios al consumo: transables",
                      "Índice de precios al consumo: no transables",
                      "Índice de precios al consumo: subyacente",
                      "Índice de precios al consumo: Winsorized 0.05"]

    if update_loc is not None:
        previous_data = ops._io(
            operation="update", data_loc=update_loc,
            name=name, index_label=index_label
        )
        output = ops._revise(new_data=output, prev_data=previous_data,
                             revise_rows=revise_rows)

    output = output.apply(pd.to_numeric, errors="coerce")
    metadata._set(output, area="Precios y salarios", currency="-",
                  inf_adj="No", unit="2010-12=100", seas_adj="NSA",
                  ts_type="-", cumperiods=1)

    if save_loc is not None:
        ops._io(operation="save", data_loc=save_loc,
                data=output, name=name, index_label=index_label)

    return output


# The `_contains_nan` function needs to be monkey-patched to avoid an error
# when checking whether a Series is True
def _new_contains_nan(a, nan_policy='propagate'):
    policies = ['propagate', 'raise', 'omit']
    if nan_policy not in policies:
        raise ValueError("nan_policy must be one of {%s}" %
                         ', '.join("'%s'" % s for s in policies))
    try:
        with np.errstate(invalid='ignore'):
            # This [0] gets the value instead of the array, fixing the error
            contains_nan = np.isnan(np.sum(a))[0]
    except TypeError:
        try:
            contains_nan = np.nan in set(a.ravel())
        except TypeError:
            contains_nan = False
            nan_policy = 'omit'
            warnings.warn("The input array could not be properly checked for "
                          "nan values. nan values will be ignored.",
                          RuntimeWarning)

    if contains_nan and nan_policy == 'raise':
        raise ValueError("The input contains nan values")

    return contains_nan, nan_policy


stats._contains_nan = _new_contains_nan
