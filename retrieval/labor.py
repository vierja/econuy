import pandas as pd

from processing import colnames, update_revise


def get(update=None, revise=0, save=None):

    file = "http://ine.gub.uy/c/document_library/get_file?uuid=50ae926c-1ddc-4409-afc6-1fecf641e3d0&groupId=10181"

    labor_raw = pd.read_excel(file, skiprows=39).dropna(axis=0, thresh=2)
    labor = labor_raw[~labor_raw["Unnamed: 0"].str.contains("-|/|Total", regex=True)]
    labor = labor[["Unnamed: 1", "Unnamed: 4", "Unnamed: 7"]]
    labor.index = pd.date_range(start="2006-01-01", periods=len(labor), freq="MS")
    labor.columns = ["LFPR", "Employment", "Unemployment"]

    if update is not None:
        labor = update_revise.upd_rev(labor, prev_data=update, revise=revise)

    labor = labor.apply(pd.to_numeric, errors="coerce")
    colnames.set_colnames(labor, area="Labor market", currency="-", inf_adj="No",
                          index="No", seas_adj="NSA", ts_type="-", cumperiods=1)

    if save is not None:
        labor.to_csv(save, sep=" ")

    return labor


if __name__ == "__main__":
    labor_mkt = get(update="../data/labor.csv", revise=6, save="../data/labor.csv")