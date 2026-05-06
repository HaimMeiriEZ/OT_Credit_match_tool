import os
import re
from tkinter import Tk, filedialog
import pandas as pd


def get_file_path(title_message):
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    file_selected = filedialog.askopenfilename(
        title=title_message,
        filetypes=[("Excel or TXT Files", "*.xlsx;*.xls;*.txt;*.csv"), ("All Files", "*.*")],
    )
    root.destroy()
    return file_selected


def get_folder_path(title_message):
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder_selected = filedialog.askdirectory(title=title_message)
    root.destroy()
    return folder_selected


def clean_card(card_val):
    if pd.isna(card_val):
        return ""
    val_str = str(card_val).strip()
    digits = re.sub(r"\D", "", val_str)
    return digits[-4:] if len(digits) >= 4 else digits


def clean_pnr(pnr_val, length=6):
    if pd.isna(pnr_val):
        return ""
    val_str = str(pnr_val).split(".")[0].strip()
    val_str = re.sub(r"\D", "", val_str).lstrip("0")
    return val_str[-length:] if len(val_str) >= length else val_str


def clean_auth(auth_val):
    if pd.isna(auth_val):
        return ""
    val_str = str(auth_val).split(".")[0].strip()
    return val_str.lstrip("0")


def clean_amount(amount_val):
    if pd.isna(amount_val):
        return 0.0
    val_str = str(amount_val).replace(",", "").strip()
    num = pd.to_numeric(val_str, errors="coerce")
    if pd.isna(num):
        return 0.0
    return round(float(num), 2)


# =====================================================================
# פונקציות קריאה וניקוי עבור כל אחד מהספקים
# =====================================================================

def load_gilboa(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            f.read()
        encoding_used = "utf-8"
    except UnicodeDecodeError:
        encoding_used = "cp1255"

    df = pd.read_csv(file_path, sep="^", dtype=str, encoding=encoding_used)
    df.columns = df.columns.astype(str).str.strip()

    if "Fop" in df.columns:
        df = df[df["Fop"].str.strip().isin(["PDQ", "CRD"])]

    # איחוד שורות לפי Doc number במידה וקיים
    if "Doc number" in df.columns:
        df["origin amount_num"] = df["origin amount"].apply(clean_amount)
        
        agg_dict = {col: "first" for col in df.columns if col != "origin amount_num"}
        agg_dict["origin amount_num"] = "sum"
        
        df = df.groupby("Doc number", as_index=False).agg(agg_dict)
        
        df["origin amount"] = df["origin amount_num"].astype(str)
        df.drop(columns=["origin amount_num"], inplace=True)

    df["match_card"] = df["Details"].apply(clean_card)
    df["match_amount"] = df["origin amount"].apply(clean_amount)
    df["match_auth"] = df["ref"].apply(clean_auth)
    df["source_supplier"] = "גלבוע"
    return df


def load_agency(file_path):
    if file_path.lower().endswith(".csv"):
        try:
            temp_df = pd.read_csv(file_path, header=None, dtype=str, encoding="utf-8")
        except UnicodeDecodeError:
            temp_df = pd.read_csv(file_path, header=None, dtype=str, encoding="cp1255")
    else:
        try:
            temp_df = pd.read_excel(file_path, header=None, dtype=str)
        except Exception:
            temp_df = pd.read_html(file_path)[0].astype(str)

    header_idx = 0
    for i, row in temp_df.iterrows():
        row_str = row.astype(str).fillna("").values
        if any("4 ספרות" in s or "סכום מטבע ראשי" in s or "מס' תיק" in s for s in row_str):
            header_idx = i
            break

    if file_path.lower().endswith(".csv"):
        try:
            df = pd.read_csv(file_path, skiprows=header_idx, dtype=str, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, skiprows=header_idx, dtype=str, encoding="cp1255")
    else:
        try:
            df = pd.read_excel(file_path, skiprows=header_idx, dtype=str)
        except Exception:
            df = pd.read_html(file_path, skiprows=header_idx)[0].astype(str)

    df.columns = df.columns.astype(str).str.strip()

    required_cols = ["4 ספרות אחרונות", "סכום מטבע ראשי", "מס' תיק", "מספר אישור"]
    for col in required_cols:
        if col not in df.columns:
            matched_col = [c for c in df.columns if col in c or c in col]
            if matched_col:
                df.rename(columns={matched_col[0]: col}, inplace=True)

    if "סוג תשלום" in df.columns:
        df = df[df["סוג תשלום"].astype(str).str.strip() == "כרטיס אשראי"]

    df = df.dropna(how="all")

    df["match_card"] = df["4 ספרות אחרונות"].apply(clean_card)
    df["match_amount"] = df["סכום מטבע ראשי"].apply(clean_amount)
    df["match_pnr"] = df["מס' תיק"].apply(lambda x: clean_pnr(x, 6))
    df["match_auth"] = df["מספר אישור"].apply(clean_auth)
    df["source_supplier"] = "אייגנסי"
    return df


def load_odyssey(file_path):
    if file_path.lower().endswith(".csv"):
        temp_df = pd.read_csv(file_path, header=None, dtype=str)
    else:
        temp_df = pd.read_excel(file_path, header=None, dtype=str)

    header_idx = 0
    for i, row in temp_df.iterrows():
        row_str = row.astype(str).values
        if any("Amount" in s for s in row_str) and any("Card" in s for s in row_str):
            header_idx = i
            break

    if file_path.lower().endswith(".csv"):
        df = pd.read_csv(file_path, skiprows=header_idx, dtype=str)
    else:
        df = pd.read_excel(file_path, skiprows=header_idx, dtype=str)

    df.columns = df.columns.astype(str).str.strip()

    df = df.dropna(subset=["Amount", "Card"], how="all")
    for col in df.columns:
        df = df[~df[col].astype(str).str.contains("Total|Summary", na=False)]

    df["match_card"] = df["Card"].apply(clean_card)
    df["match_amount"] = df["Amount"].apply(clean_amount)
    df["match_pnr"] = df["Pnr"].apply(lambda x: clean_pnr(x, 6))
    df["match_auth"] = ""
    df["source_supplier"] = "אודיסאה"
    return df


def load_booster(file_path):
    if file_path.lower().endswith(".csv"):
        df = pd.read_csv(file_path, skiprows=6, dtype=str)
    else:
        df = pd.read_excel(file_path, skiprows=6, dtype=str)
        
    df.columns = df.columns.astype(str).str.strip()

    if "Payment Method" in df.columns:
        df = df[df["Payment Method"].astype(str).str.strip().str.lower().str.startswith("credit card", na=False)]

    # איחוד שורות לפי Document No. במידה וקיים
    if "Document No." in df.columns:
        df["Amount_num"] = df["Amount"].apply(clean_amount)
        
        agg_dict = {col: "first" for col in df.columns if col != "Amount_num"}
        agg_dict["Amount_num"] = "sum"
        
        df = df.groupby("Document No.", as_index=False).agg(agg_dict)
        
        df["Amount"] = df["Amount_num"].astype(str)
        df.drop(columns=["Amount_num"], inplace=True)

    df["match_card"] = df["Payment Method"].apply(clean_card)
    df["match_amount"] = df["Amount"].apply(clean_amount)
    df["match_pnr"] = df["Credit Account Name"].apply(lambda x: clean_pnr(x, 6))
    df["match_auth"] = df["Description"].apply(clean_auth)
    df["source_supplier"] = "בוסטר"
    return df


# =====================================================================
# טעינה וסיווג לקובץ "קרדיט 2000"
# =====================================================================

def load_credit_2000(file_path):
    df = pd.read_excel(file_path, dtype=str)
    df.columns = df.columns.astype(str).str.strip()

    df["מסוף_נקי"] = df["מסוף"].astype(str).str.strip().str.lower()
    df["מספר הזמנה_נקי"] = df["מספר הזמנה"].astype(str).str.strip()

    def classify_supplier(row):
        terminal = row["מסוף_נקי"]
        order_no = row["מספר הזמנה_נקי"]

        if terminal in ["cus0896", "cus0899", "cus0002"]:
            return "אייגנסי"
        if terminal in ["cus2343", "cus2798"]:
            return "אודיסאה"
        
        if terminal == "cus0855":
            if order_no.startswith("00"):
                return "בוסטר"
            return "גלבוע"

        gilboa_terminals = [
            "cus0853", "cus0856", "cus0862", "cus0865", "cus0866",
            "cus0870", "cus0871", "cus0874", "cus0879", "cus0881",
            "cus0884", "cus2097", "cus2479", "cus3130", "cus3444"
        ]
        if terminal in gilboa_terminals:
            return "גלבוע"
        return "לא מזוהה"

    df["ספק_משויך"] = df.apply(classify_supplier, axis=1)
    df = df[df["ספק_משויך"] != "לא מזוהה"]

    df["match_card"] = df["טוקן"].apply(clean_card)
    df["match_amount"] = df["סכום"].apply(clean_amount)

    if "מספר אישור" in df.columns:
        df["match_auth"] = df["מספר אישור"].apply(clean_auth)
    else:
        df["match_auth"] = ""

    def extract_credit_pnr(row):
        pnr_raw = str(row["מספר הזמנה_נקי"]).split(".")[0].strip()
        pnr_str = re.sub(r"\D", "", pnr_raw)
        
        if row["ספק_משויך"] == "גלבוע":
            return pnr_str.lstrip("0")[:8]
        
        pnr_clean = pnr_str.lstrip("0")
        return pnr_clean[-6:] if len(pnr_clean) >= 6 else pnr_clean

    df["match_pnr"] = df.apply(extract_credit_pnr, axis=1)
    return df


# =====================================================================
# תהליך ההתאמה הראשי
# =====================================================================

def run_reconciliation():
    credit_file = get_file_path("בחר את קובץ קרדיט 2000")
    if not credit_file: return

    input_folder = get_folder_path("בחר את תיקיית הספקים")
    if not input_folder: return

    output_folder = get_folder_path("בחר תיקיית פלט לשמירת דוחות ההתאמה")
    if not output_folder: return

    files_in_input = os.listdir(input_folder)

    gilboa_file = None
    agency_file = None
    odyssey_file = None
    booster_file = None

    for f in files_in_input:
        if f.startswith("~$"): continue
        f_lower = f.lower()
        f_path = os.path.join(input_folder, f)

        if "גלבוע" in f or "gilboa" in f_lower:
            gilboa_file = f_path
        elif "אייגנסי" in f or "agency" in f_lower:
            agency_file = f_path
        elif "אודיסאה" in f or "odyssey" in f_lower or "קבלות אודיסאה" in f_lower:
            odyssey_file = f_path
        elif "בוסטר" in f or "booster" in f_lower:
            booster_file = f_path

    df_credit = load_credit_2000(credit_file)

    suppliers_dfs = []
    if gilboa_file: suppliers_dfs.append(load_gilboa(gilboa_file))
    if agency_file: suppliers_dfs.append(load_agency(agency_file))
    if odyssey_file: suppliers_dfs.append(load_odyssey(odyssey_file))
    if booster_file: suppliers_dfs.append(load_booster(booster_file))

    if not suppliers_dfs: return

    df_all_suppliers = pd.concat(suppliers_dfs, ignore_index=True)

    df_credit["credit_uid"] = range(len(df_credit))
    df_all_suppliers["supplier_uid"] = range(len(df_all_suppliers))

    # 1. התאמה עבור גלבוע
    matched_gilboa = pd.merge(
        df_credit[df_credit["ספק_משויך"] == "גלבוע"],
        df_all_suppliers[df_all_suppliers["source_supplier"] == "גלבוע"],
        left_on=["match_card", "match_amount", "match_auth", "ספק_משויך"],
        right_on=["match_card", "match_amount", "match_auth", "source_supplier"],
        how="inner"
    )

    # 2. התאמה עבור אייגנסי ובוסטר
    matched_with_auth = pd.merge(
        df_credit[df_credit["ספק_משויך"].isin(["אייגנסי", "בוסטר"])],
        df_all_suppliers[df_all_suppliers["source_supplier"].isin(["אייגנסי", "בוסטר"])],
        left_on=["match_card", "match_amount", "match_pnr", "match_auth", "ספק_משויך"],
        right_on=["match_card", "match_amount", "match_pnr", "match_auth", "source_supplier"],
        how="inner",
    )

    # 3. התאמה עבור אודיסאה
    matched_odyssey = pd.merge(
        df_credit[df_credit["ספק_משויך"] == "אודיסאה"],
        df_all_suppliers[df_all_suppliers["source_supplier"] == "אודיסאה"],
        left_on=["match_card", "match_amount", "match_pnr", "ספק_משויך"],
        right_on=["match_card", "match_amount", "match_pnr", "source_supplier"],
        how="inner",
    )

    matched_all = pd.concat([matched_gilboa, matched_with_auth, matched_odyssey], ignore_index=True)
    matched_all = matched_all.drop_duplicates(subset=["credit_uid", "supplier_uid"])

    matched_credit_uids = matched_all["credit_uid"].unique()
    df_only_in_credit = df_credit[~df_credit["credit_uid"].isin(matched_credit_uids)]

    matched_supplier_uids = matched_all["supplier_uid"].unique()
    df_only_in_suppliers = df_all_suppliers[~df_all_suppliers["supplier_uid"].isin(matched_supplier_uids)]

    # =====================================================================
    # יצירת דוחות ספציפיים לפי עמודות מבוקשות
    # =====================================================================
    
    credit_cols = ["מסוף", "טוקן", "מספר אישור", "סכום", "מספר הזמנה", "ספק_משויך"]

    for col in credit_cols:
        if col not in df_credit.columns:
            df_credit[col] = ""

    supplier_cols_dict = {
        "בוסטר": ["Payment Method", "Amount", "Credit Account Name", "Description"],
        "אייגנסי": ["4 ספרות אחרונות", "סכום מטבע ראשי", "מס' תיק", "מספר אישור"],
        "אודיסאה": ["Card", "Amount", "Pnr"],
        "גלבוע": ["Details", "origin amount", "ref"]
    }

    path_matched = os.path.join(output_folder, "1_התאמה_מלאה.xlsx")
    path_credit = os.path.join(output_folder, "2_רק_בקרדיט_2000.xlsx")
    path_suppliers = os.path.join(output_folder, "3_רק_בדוחות_הספקים.xlsx")

    # --- יצירת קובץ 1: התאמה מלאה ---
    with pd.ExcelWriter(path_matched, engine="openpyxl") as writer:
        has_sheets = False
        for supplier, sup_cols in supplier_cols_dict.items():
            df_sup_matched = matched_all[matched_all["ספק_משויך"] == supplier].copy()
            if not df_sup_matched.empty:
                rename_map = {}
                for c in credit_cols:
                    if c in df_sup_matched.columns:
                        rename_map[c] = f"{c} - קרדיט"
                    elif f"{c}_x" in df_sup_matched.columns:
                        rename_map[f"{c}_x"] = f"{c} - קרדיט"
                    elif f"{c}_y" in df_sup_matched.columns:
                        rename_map[f"{c}_y"] = f"{c} - קרדיט"

                for c in sup_cols:
                    if c in df_sup_matched.columns:
                        rename_map[c] = f"{c} - {supplier}"
                    elif f"{c}_y" in df_sup_matched.columns:
                        rename_map[f"{c}_y"] = f"{c} - {supplier}"
                    elif f"{c}_x" in df_sup_matched.columns:
                        rename_map[f"{c}_x"] = f"{c} - {supplier}"

                df_sup_matched.rename(columns=rename_map, inplace=True)

                current_credit_cols = [f"{c} - קרדיט" for c in credit_cols if f"{c} - קרדיט" in df_sup_matched.columns]
                current_sup_cols = [f"{c} - {supplier}" for c in sup_cols if f"{c} - {supplier}" in df_sup_matched.columns]

                final_cols = current_credit_cols + current_sup_cols
                df_sup_matched[final_cols].to_excel(writer, sheet_name=supplier, index=False)
                has_sheets = True
        
        if not has_sheets:
            pd.DataFrame(columns=[f"{c} - קרדיט" for c in credit_cols]).to_excel(writer, sheet_name="אין נתונים", index=False)

    # --- יצירת קובץ 2: רק בקרדיט 2000 ---
    df_only_in_credit_clean = df_only_in_credit[credit_cols].copy()
    df_only_in_credit_clean.to_excel(path_credit, index=False)

    # --- יצירת קובץ 3: רק בדוחות הספקים ---
    with pd.ExcelWriter(path_suppliers, engine="openpyxl") as writer:
        has_sheets_sup = False
        for supplier, sup_cols in supplier_cols_dict.items():
            df_sup_missing = df_only_in_suppliers[df_only_in_suppliers["source_supplier"] == supplier].copy()
            if not df_sup_missing.empty:
                current_sup_cols = [c for c in sup_cols if c in df_sup_missing.columns]
                if current_sup_cols:
                    df_sup_missing[current_sup_cols].to_excel(writer, sheet_name=supplier, index=False)
                    has_sheets_sup = True
                    
        if not has_sheets_sup:
            pd.DataFrame(columns=["אין נתונים"]).to_excel(writer, sheet_name="אין נתונים", index=False)

    print(f"\nהדוחות נוצרו בהצלחה בתיקייה: {output_folder}")


if __name__ == "__main__":
    run_reconciliation()