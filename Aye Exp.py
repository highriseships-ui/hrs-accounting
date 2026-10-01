import streamlit as st
import pandas as pd
import requests
import io
import json
import re
import time
from datetime import datetime, timedelta

# --- PAGE SETUP ---
st.set_page_config(page_title="Accounts", layout="wide")

# --- DROPBOX SECRETS ---
APP_KEY = "qhr6rp2zfh80wr4"
APP_SECRET = "cbtc7622x0iredv"
REFRESH_TOKEN = "RllXcIlTtSkAAAAAAAAAAYr1zV5lYqBUycJKOLVLVpiG7t7sorNAbn1bINyn6cHj"

# --- DROPBOX PATHS ---
EXPENSES_PATH = "/expenses.csv"
WALLETS_PATH = "/wallets.csv"
LOG_PATH = "/access_log.csv"
VESSELS_PATH = "/vessels.csv"
SETTINGS_PATH = "/settings.json"
WALLET_HISTORY_PATH = "/wallet_history.csv"
AUDIT_PATH = "/audit_log.csv"

# --- SESSION STATES ---
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "user_role" not in st.session_state: st.session_state.user_role = None
if "curr_page" not in st.session_state: st.session_state.curr_page = 1
if "prev_search" not in st.session_state: st.session_state.prev_search = ""
if "prev_vessel" not in st.session_state: st.session_state.prev_vessel = ""

# --- DROPBOX CORE FUNCTIONS ---
def get_access_token():
    url = "https://api.dropbox.com/oauth2/token"
    data = {"grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN, "client_id": APP_KEY, "client_secret": APP_SECRET}
    res = requests.post(url, data=data)
    return res.json()["access_token"] if res.status_code == 200 else None

def download_file(file_path):
    token = get_access_token()
    if not token: return None
    headers = {"Authorization": f"Bearer {token}", "Dropbox-API-Arg": json.dumps({"path": file_path})}
    res = requests.post("https://content.dropboxapi.com/2/files/download", headers=headers)
    return res.text if res.status_code == 200 else None

def upload_file(content, file_path):
    token = get_access_token()
    if not token: return
    headers = {
        "Authorization": f"Bearer {token}",
        "Dropbox-API-Arg": json.dumps({"path": file_path, "mode": "overwrite"}),
        "Content-Type": "application/octet-stream"
    }
    requests.post("https://content.dropboxapi.com/2/files/upload", headers=headers, data=content.encode('utf-8'))

def upload_binary(file_obj, file_path):
    try:
        token = get_access_token()
        if not token: return False
        
        api_arg = json.dumps({"path": file_path, "mode": "overwrite"}).encode('ascii', 'ignore').decode('ascii')
        headers = {
            "Authorization": f"Bearer {token}",
            "Dropbox-API-Arg": api_arg,
            "Content-Type": "application/octet-stream"
        }
        file_obj.seek(0)
        res = requests.post("https://content.dropboxapi.com/2/files/upload", headers=headers, data=file_obj, timeout=120)
        if res.status_code == 200:
            return True
        else:
            st.error(f"Dropbox Error: Could not upload file. {res.text}")
            return False
    except Exception as e:
        st.error(f"Upload Error: Connection interrupted. {str(e)}")
        return False

def get_temp_link(file_path):
    token = get_access_token()
    if not token: return None
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    res = requests.post("https://api.dropboxapi.com/2/files/get_temporary_link", headers=headers, json={"path": file_path})
    if res.status_code == 200:
        return res.json().get("link")
    return None

# --- INITIALIZATION ---
def init_data():
    settings_data = download_file(SETTINGS_PATH)
    if settings_data:
        st.session_state.settings = json.loads(settings_data)
        needs_update = False
        if "assistant_pin" not in st.session_state.settings: 
            st.session_state.settings["assistant_pin"] = "3576"
            needs_update = True
        if len(st.session_state.settings.get("master_pin", "")) != 6:
            st.session_state.settings["master_pin"] = "131509"
            needs_update = True
            
        if needs_update:
            upload_file(json.dumps(st.session_state.settings), SETTINGS_PATH)
    else:
        st.session_state.settings = {"master_pin": "131509", "assistant_pin": "3576", "manager_pin": "5678"}
        upload_file(json.dumps(st.session_state.settings), SETTINGS_PATH)

    vessels_csv = download_file(VESSELS_PATH)
    if vessels_csv:
        st.session_state.vessels = pd.read_csv(io.StringIO(vessels_csv))["Vessels"].tolist()
    else:
        st.session_state.vessels = ["Phoenix", "Kingfisher", "Falcon I", "Arya"]
        upload_file(pd.DataFrame({"Vessels": st.session_state.vessels}).to_csv(index=False), VESSELS_PATH)

    w_csv = download_file(WALLETS_PATH)
    if w_csv:
        w_df = pd.read_csv(io.StringIO(w_csv))
        w_df["Person"] = w_df["Person"].replace({"Owner J": "Assistant"})
        st.session_state.wallets = dict(zip(w_df["Person"], w_df["Balance"]))
    else:
        st.session_state.wallets = {"Owner A": 500000.0, "Assistant": 100000.0, "Manager": 40000.0}
    
    e_csv = download_file(EXPENSES_PATH)
    if e_csv:
        st.session_state.expenses = pd.read_csv(io.StringIO(e_csv))
        if "ID" not in st.session_state.expenses.columns: st.session_state.expenses.insert(0, "ID", range(1, 1 + len(st.session_state.expenses)))
        if "Receipt" not in st.session_state.expenses.columns: st.session_state.expenses["Receipt"] = "No"
        if "Entered By" not in st.session_state.expenses.columns: st.session_state.expenses["Entered By"] = "Master"
    else:
        st.session_state.expenses = pd.DataFrame(columns=["ID", "Date", "Vessel", "Category", "Item", "Paid By", "Amount", "Expiry Date", "Receipt", "Entered By"])

def write_audit(action, eid, details):
    a_csv = download_file(AUDIT_PATH)
    df_audit = pd.read_csv(io.StringIO(a_csv)) if a_csv else pd.DataFrame(columns=["Timestamp", "User", "Action", "Expense ID", "Details"])
    new_audit = pd.DataFrame([{"Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "User": st.session_state.user_role, "Action": action, "Expense ID": eid, "Details": details}])
    df_audit = pd.concat([df_audit, new_audit], ignore_index=True)
    upload_file(df_audit.to_csv(index=False), AUDIT_PATH)

# --- LOGIN SCREEN & FORGOT PASSWORD ---
def login_screen():
    st.title("🔒 Login")
    if "settings" not in st.session_state: init_data()
    
    pin = st.text_input("Enter PIN", type="password")
    if st.button("Login"):
        if pin == st.session_state.settings["master_pin"]:
            st.session_state.authenticated = True; st.session_state.user_role = "Master"; st.rerun()
        elif pin == st.session_state.settings["assistant_pin"]:
            st.session_state.authenticated = True; st.session_state.user_role = "Assistant"; st.rerun()
        elif pin == st.session_state.settings["manager_pin"]:
            st.session_state.authenticated = True; st.session_state.user_role = "Manager"; st.rerun()
        else:
            st.error("Invalid PIN")
            
    st.divider()
    if st.button("Forgot Password?"):
        st.session_state.show_forgot = not st.session_state.get("show_forgot", False)
        
    if st.session_state.get("show_forgot", False):
        st.info("🔐 Fail-Safe Password Override System")
        st.write("If your account is hacked or you forget your PIN, enter your authorized email below. This will act as a secret key to instantly reset the password.")
        recovery_email = st.text_input("Enter the authorized Master recovery email address:")
        
        if st.button("Activate Override"):
            if recovery_email.strip().lower() == "hettyvaz2004@yahoo.co.in":
                st.session_state.settings["master_pin"] = "181112"
                upload_file(json.dumps(st.session_state.settings), SETTINGS_PATH)
                st.success("Sent. Please use the new emergency PIN.")
            else:
                st.error("❌ Unauthorized email address. Access denied.")

# --- APP LOGIC START ---
if not st.session_state.authenticated:
    login_screen()
else:
    if "expenses" not in st.session_state: init_data()

    # --- SIDEBAR & GOLD 3D LOGO ---
    st.sidebar.markdown("""
        <div style="background-color: #fdfbf7; padding: 25px 15px 15px 15px; border-radius: 10px; text-align: center; box-shadow: 0px 4px 15px rgba(0,0,0,0.15); margin-bottom: 20px; border: 1px solid #eae5d9;">
            <div style="font-family: 'Brush Script MT', 'Lucida Handwriting', cursive; font-size: 52px; font-weight: bold; background: linear-gradient(to right, #aa771c, #d4af37, #fdf5c9, #d4af37, #8a5a19); -webkit-background-clip: text; -webkit-text-fill-color: transparent; filter: drop-shadow(2px 4px 2px rgba(0,0,0,0.25)); line-height: 1;">
                Air<br>Ayesha
            </div>
            <div style="margin-top: -15px;">
                <svg width="160" height="40" viewBox="0 0 160 40" style="overflow: visible; filter: drop-shadow(1px 2px 2px rgba(0,0,0,0.3));">
                    <path d="M10,30 Q80,5 140,30" fill="transparent" stroke="url(#gold)" stroke-width="4" stroke-linecap="round"/>
                    <defs><linearGradient id="gold" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#aa771c" /><stop offset="50%" stop-color="#fdf5c9" /><stop offset="100%" stop-color="#d4af37" /></linearGradient></defs>
                    <text x="135" y="34" font-size="24">🚢</text>
                </svg>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    if st.sidebar.button("Logout"): st.session_state.authenticated = False; st.rerun()
    st.sidebar.divider()

    if st.session_state.user_role == "Master":
        st.sidebar.title("💰 Live Wallets")
        for person, balance in st.session_state.wallets.items():
            st.sidebar.metric(label=person, value=f"₹ {balance:,.2f}")
        
        with st.sidebar.expander("➕ Add Funds to Wallet"):
            fund_person = st.selectbox("Select Wallet", list(st.session_state.wallets.keys()), key="f_per")
            fund_amount = st.number_input("Amount to Add (₹)", min_value=0.0, format="%.2f")
            fund_reason = st.text_input("Reason (e.g. Cash given today)")
            if st.button("Add Funds") and fund_amount > 0:
                st.session_state.wallets[fund_person] += fund_amount
                upload_file(pd.DataFrame(list(st.session_state.wallets.items()), columns=["Person", "Balance"]).to_csv(index=False), WALLETS_PATH)
                new_hist = pd.DataFrame([{"Date": datetime.now().strftime("%Y-%m-%d"), "Wallet": fund_person, "Added": fund_amount, "Reason": fund_reason}])
                old_hist_csv = download_file(WALLET_HISTORY_PATH)
                updated_hist = pd.concat([pd.read_csv(io.StringIO(old_hist_csv)), new_hist], ignore_index=True) if old_hist_csv else new_hist
                upload_file(updated_hist.to_csv(index=False), WALLET_HISTORY_PATH)
                st.success(f"Added ₹{fund_amount} to {fund_person}!")
                time.sleep(1.5)
                st.rerun()

        with st.sidebar.expander("⚙️ Admin Settings"):
            st.warning("Master PIN MUST be 6 digits. Assistant and Manager PINs MUST be 4 digits.")
            new_master = st.text_input("Master PIN (6 digits)", value=st.session_state.settings["master_pin"])
            new_assistant = st.text_input("Assistant PIN (4 digits)", value=st.session_state.settings["assistant_pin"])
            new_manager = st.text_input("Manager PIN (4 digits)", value=st.session_state.settings["manager_pin"])
            
            if st.button("Save PINs"):
                if len(new_master) != 6 or not new_master.isdigit():
                    st.error("❌ Master PIN must be exactly 6 numbers!")
                elif len(new_assistant) != 4 or not new_assistant.isdigit() or len(new_manager) != 4 or not new_manager.isdigit():
                    st.error("❌ Assistant and Manager PINs must be exactly 4 numbers!")
                else:
                    st.session_state.settings = {"master_pin": new_master, "assistant_pin": new_assistant, "manager_pin": new_manager}
                    upload_file(json.dumps(st.session_state.settings), SETTINGS_PATH)
                    st.success("✅ PINs updated securely!")
                
    st.sidebar.caption("Software Version: v2.4")

    # --- MAIN APP TITLE ---
    st.title("⚓ Accounts")
    st.caption(f"Logged in as: **{st.session_state.user_role}**")

    col1, col2 = st.columns([3,1])
    with col1: 
        current_vessel = st.selectbox("Select Active Project", st.session_state.vessels)
        if st.session_state.prev_vessel != current_vessel:
            st.session_state.curr_page = 1
            st.session_state.prev_vessel = current_vessel
            
    if st.session_state.user_role == "Master":
        with col2:
            with st.expander("➕ Add New Vessel"):
                new_v = st.text_input("Vessel Name")
                if st.button("Add") and new_v and new_v not in st.session_state.vessels:
                    st.session_state.vessels.append(new_v)
                    upload_file(pd.DataFrame({"Vessels": st.session_state.vessels}).to_csv(index=False), VESSELS_PATH)
                    st.rerun()

    # --- SHARED FUNCTIONS ---
    def reshuffle_ids():
        if not st.session_state.expenses.empty:
            st.session_state.expenses = st.session_state.expenses.reset_index(drop=True)
            st.session_state.expenses["ID"] = range(1, len(st.session_state.expenses) + 1)

    def save_expense(vessel, category, item, paid_by, amount, expiry_date=None, receipt_file=None):
        st.session_state.wallets[paid_by] -= amount
        upload_file(pd.DataFrame(list(st.session_state.wallets.items()), columns=["Person", "Balance"]).to_csv(index=False), WALLETS_PATH)
        
        receipt_status = "No"
        if receipt_file is not None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = receipt_file.name.split('.')[-1].lower()
            safe_vessel = re.sub(r'[^A-Za-z0-9]', '_', vessel)
            dbx_path = f"/Receipts/{safe_vessel}/Receipt_{ts}.{ext}"
            
            with st.spinner("Uploading receipt to secure cloud. Please wait..."):
                if upload_binary(receipt_file, dbx_path):
                    receipt_status = dbx_path
                else:
                    st.error("Failed to upload the receipt. Saving entry without receipt.")

        new_row = pd.DataFrame([{"ID": 0, "Date": datetime.now().strftime("%Y-%m-%d"), "Vessel": vessel, "Category": category, "Item": item, "Paid By": paid_by, "Amount": amount, "Expiry Date": expiry_date, "Receipt": receipt_status, "Entered By": st.session_state.user_role}])
        st.session_state.expenses = pd.concat([st.session_state.expenses, new_row], ignore_index=True)
        reshuffle_ids()
        upload_file(st.session_state.expenses.to_csv(index=False), EXPENSES_PATH)
        st.success("Expense Saved Successfully!")
        time.sleep(1.5)
        st.rerun()

    def expense_form(category_name):
        with st.form(f"f_{category_name}", clear_on_submit=True):
            item = st.text_input("Description")
            amount = st.number_input("Amount (₹)", min_value=0.0, format="%.2f")
            
            if st.session_state.user_role == "Master": paid_by = st.selectbox("Paid By", list(st.session_state.wallets.keys()))
            elif st.session_state.user_role == "Assistant": paid_by = st.selectbox("Paid By", ["Assistant"])
            else: paid_by = st.selectbox("Paid By", ["Manager"])
                
            receipt = st.file_uploader("Attach Bill (Optional)", type=["png", "jpg", "jpeg", "pdf"])
            if st.form_submit_button("Save Expense") and item and amount > 0:
                save_expense(current_vessel, category_name, item, paid_by, amount, receipt_file=receipt)

    def render_summary_and_edit():
        st.write(f"### Expenditures for {current_vessel}")
        
        search_query = st.text_input("🔍 Search Entries (e.g., 'transport')", key="search_bar")
        if st.session_state.prev_search != search_query:
            st.session_state.curr_page = 1
            st.session_state.prev_search = search_query
            
        if st.session_state.user_role == "Master":
            v_data = st.session_state.expenses[st.session_state.expenses["Vessel"] == current_vessel]
        elif st.session_state.user_role == "Assistant":
            v_data = st.session_state.expenses[(st.session_state.expenses["Vessel"] == current_vessel) & (st.session_state.expenses["Entered By"].isin(["Assistant", "Manager"]))]
        else:
            v_data = st.session_state.expenses[(st.session_state.expenses["Vessel"] == current_vessel) & (st.session_state.expenses["Entered By"] == "Manager")]
            
        if search_query: v_data = v_data[v_data['Item'].astype(str).str.contains(search_query, case=False, na=False)]
            
        col_m1, col_m2 = st.columns(2)
        with col_m1: st.metric("Total Expense Shown", f"₹ {v_data['Amount'].sum():,.2f}")
        with col_m2: st.download_button("⬇️ Download CSV", data=v_data.to_csv(index=False).encode('utf-8'), file_name=f"{current_vessel}_expenses.csv", mime="text/csv", key="dl_btn")

        st.divider()
        page_size_str = st.selectbox("Rows per page", ["10", "25", "50", "100", "All"], index=1, key="psize")
        
        if page_size_str != "All":
            page_size = int(page_size_str)
            total_pages = max(1, (len(v_data) - 1) // page_size + 1)
            if st.session_state.curr_page > total_pages: st.session_state.curr_page = total_pages
            
            start_idx = (st.session_state.curr_page - 1) * page_size
            df_page = v_data.iloc[start_idx : start_idx + page_size]
            
            pc1, pc2, pc3 = st.columns([1,2,1])
            with pc1:
                if st.button("⬅️ Previous") and st.session_state.curr_page > 1:
                    st.session_state.curr_page -= 1; st.rerun()
            with pc2: st.markdown(f"<div style='text-align: center'>Page {st.session_state.curr_page} of {total_pages}</div>", unsafe_allow_html=True)
            with pc3:
                if st.button("Next ➡️") and st.session_state.curr_page < total_pages:
                    st.session_state.curr_page += 1; st.rerun()
        else:
            df_page = v_data

        df_display = df_page.copy()
        def clean_receipt_status(x):
            s = str(x)
            if s in ["No", "nan", "None", ""]: return "No"
            return "Yes"
        df_display["Receipt"] = df_display["Receipt"].apply(clean_receipt_status)
        df_display.insert(0, "Select", False) 
        
        st.info("💡 Tick the top-left box to select all on this page. Tick individual rows to Edit, Move, Delete, or Attach Bills.")
        edited_df = st.data_editor(df_display, hide_index=True, use_container_width=True, disabled=v_data.columns.tolist(), key="editor")
        
        selected_ids = edited_df[edited_df["Select"]]["ID"].tolist()
        
        if selected_ids:
            st.divider()
            st.write(f"### ⚙️ Actions for Selected ({len(selected_ids)} items)")
            
            # --- EDIT & MOVE LOGIC (1 ITEM ONLY) ---
            if len(selected_ids) == 1:
                edit_id = selected_ids[0]
                row_idx = st.session_state.expenses.index[st.session_state.expenses['ID'] == edit_id].tolist()[0]
                row_data = st.session_state.expenses.iloc[row_idx]
                
                with st.form("edit_entry_form"):
                    st.write("#### ✏️ Edit Entry Details")
                    c1, c2 = st.columns(2)
                    with c1: new_item = st.text_input("Edit Description Text", value=str(row_data['Item']))
                    with c2: new_amt = st.number_input("Edit Amount (₹)", value=float(row_data['Amount']))
                    if st.form_submit_button("💾 Update Entry Details"):
                        old_amt = float(row_data['Amount'])
                        old_txt = str(row_data['Item'])
                        st.session_state.wallets[row_data['Paid By']] += old_amt 
                        st.session_state.wallets[row_data['Paid By']] -= new_amt 
                        upload_file(pd.DataFrame(list(st.session_state.wallets.items()), columns=["Person", "Balance"]).to_csv(index=False), WALLETS_PATH)
                        st.session_state.expenses.at[row_idx, 'Item'] = new_item
                        st.session_state.expenses.at[row_idx, 'Amount'] = new_amt
                        upload_file(st.session_state.expenses.to_csv(index=False), EXPENSES_PATH)
                        write_audit("EDIT", edit_id, f"Changed '{old_txt}' (₹{old_amt}) to '{new_item}' (₹{new_amt})")
                        st.success("Entry Updated!")
                        time.sleep(1.5)
                        st.rerun()

                if st.session_state.user_role == "Master":
                    with st.form("transfer_form"):
                        st.write("#### 🔄 Transfer or Duplicate Entry")
                        t_col1, t_col2 = st.columns(2)
                        with t_col1: target_vessel = st.selectbox("Target Vessel", st.session_state.vessels)
                        with t_col2: action = st.radio("Action", ["Move to Vessel", "Duplicate Entry"], horizontal=True)
                        if st.form_submit_button("Execute Action"):
                            if action == "Move to Vessel":
                                old_vessel = row_data['Vessel']
                                if old_vessel != target_vessel:
                                    st.session_state.expenses.at[row_idx, 'Vessel'] = target_vessel
                                    upload_file(st.session_state.expenses.to_csv(index=False), EXPENSES_PATH)
                                    write_audit("MOVE", edit_id, f"Moved from {old_vessel} to {target_vessel}")
                                    st.success(f"Successfully moved to {target_vessel}!")
                                    time.sleep(1.5)
                                    st.rerun()
                                else:
                                    st.warning("Entry is already in this vessel.")
                            else:
                                new_row = row_data.copy()
                                new_row['Vessel'] = target_vessel
                                new_row['ID'] = 0 
                                st.session_state.wallets[new_row['Paid By']] -= float(new_row['Amount'])
                                upload_file(pd.DataFrame(list(st.session_state.wallets.items()), columns=["Person", "Balance"]).to_csv(index=False), WALLETS_PATH)
                                st.session_state.expenses = pd.concat([st.session_state.expenses, pd.DataFrame([new_row])], ignore_index=True)
                                reshuffle_ids()
                                upload_file(st.session_state.expenses.to_csv(index=False), EXPENSES_PATH)
                                write_audit("DUPLICATE", edit_id, f"Duplicated copy sent to {target_vessel}")
                                st.success(f"Duplicated to {target_vessel}!")
                                time.sleep(1.5)
                                st.rerun()

                # View Multi-Receipt Logic
                rcpt_val = str(row_data['Receipt'])
                if rcpt_val not in ["No", "nan", "None", ""]:
                    st.write("#### 📄 Attached Document(s)")
                    if rcpt_val == "Yes":
                        st.warning("This is an older 'legacy' receipt. Please re-upload the bill below to view it online.")
                    else:
                        if st.button("👁️ Fetch Secure Document Links", key="btn_view_rcpt"):
                            with st.spinner("Fetching secure links from Dropbox..."):
                                # Split by the pipe character in case there are multiple files attached!
                                paths = rcpt_val.split('|')
                                for i, path in enumerate(paths):
                                    link = get_temp_link(path)
                                    st.write(f"**Document {i+1}**")
                                    if link:
                                        ext = path.split('.')[-1].lower()
                                        if ext in ['png', 'jpg', 'jpeg']:
                                            st.image(link, caption=f"Image {i+1}")
                                            st.markdown(f"**[👉 Download Image {i+1}]({link})**")
                                        elif ext == 'pdf':
                                            st.success(f"📄 PDF {i+1} Ready!")
                                            st.markdown(f'<a href="{link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #00ffcc; color: black; text-align: center; text-decoration: none; font-weight: bold; border-radius: 5px; margin-bottom: 10px;">📄 View/Download PDF {i+1}</a>', unsafe_allow_html=True)
                                        else:
                                            st.markdown(f"**[👉 Download File {i+1}]({link})**")
                                    else:
                                        st.error(f"Could not fetch document {i+1}. It may have been deleted from Dropbox.")
                                st.divider()
            
            # --- BULK MULTI-RECEIPT UPLOAD ---
            with st.form("bulk_receipt_form", clear_on_submit=True):
                st.write("#### 📎 Attach Additional Receipt to Selected")
                bulk_receipt = st.file_uploader("Upload Bill (Applies to all selected)", type=["png", "jpg", "jpeg", "pdf"])
                if st.form_submit_button("Upload & Link Receipt") and bulk_receipt:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    ext = bulk_receipt.name.split('.')[-1].lower()
                    safe_vessel = re.sub(r'[^A-Za-z0-9]', '_', current_vessel)
                    dbx_path = f"/Receipts/{safe_vessel}/Bulk_{ts}.{ext}"
                    
                    with st.spinner("Uploading file securely to Dropbox. This may take a minute for PDFs..."):
                        success = upload_binary(bulk_receipt, dbx_path)
                        
                    if success:
                        for eid in selected_ids:
                            r_idx = st.session_state.expenses.index[st.session_state.expenses['ID'] == eid].tolist()[0]
                            old_val = str(st.session_state.expenses.at[r_idx, 'Receipt'])
                            # If it's a legacy or empty entry, just replace it
                            if old_val in ["No", "nan", "None", "", "Yes"]:
                                st.session_state.expenses.at[r_idx, 'Receipt'] = dbx_path
                            else:
                                # CHAIN IT TOGETHER! Append the new path with a pipe symbol separator
                                st.session_state.expenses.at[r_idx, 'Receipt'] = old_val + "|" + dbx_path
                                
                        upload_file(st.session_state.expenses.to_csv(index=False), EXPENSES_PATH)
                        write_audit("RECEIPT UPLOADED", str(selected_ids), "Attached additional receipt to selected rows.")
                        st.success("✅ Receipt successfully linked and added to the list!")
                        time.sleep(1.5)
                        st.rerun()

            # --- DELETE SELECTED ---
            with st.form("delete_form"):
                st.write("#### 🗑 Delete Selected")
                if st.form_submit_button("Delete Entries Entirely", type="primary"):
                    rows_to_drop = []
                    for eid in selected_ids:
                        r_idx = st.session_state.expenses.index[st.session_state.expenses['ID'] == eid].tolist()[0]
                        r_data = st.session_state.expenses.iloc[r_idx]
                        st.session_state.wallets[r_data['Paid By']] += float(r_data['Amount']) 
                        rows_to_drop.append(r_idx)
                        write_audit("DELETE", eid, f"Deleted: '{r_data['Item']}' (₹{r_data['Amount']} paid by {r_data['Paid By']})")
                    
                    st.session_state.expenses = st.session_state.expenses.drop(rows_to_drop)
                    reshuffle_ids() 
                    upload_file(pd.DataFrame(list(st.session_state.wallets.items()), columns=["Person", "Balance"]).to_csv(index=False), WALLETS_PATH)
                    upload_file(st.session_state.expenses.to_csv(index=False), EXPENSES_PATH)
                    st.error("Entries completely deleted, IDs reshuffled, and money refunded.")
                    time.sleep(2)
                    st.rerun()

    # --- TAB LOGIC BASED ON ROLE ---
    if st.session_state.user_role == "Master":
        tabs = st.tabs(["📊 Overall", "🛠️ Maintenance", "🚚 Transport", "📦 Purchases", "🧾 Billings", "📥 Bulk Import", "📜 Audit History"])
        
        with tabs[0]: render_summary_and_edit() 
        with tabs[1]: expense_form("Maintenance & Repair")
        with tabs[2]: expense_form("Transportation")
        with tabs[3]: expense_form("Purchases (Spares)")
        with tabs[4]:
            b_type = st.selectbox("Type", ["Hard Charges", "Electricity", "Monthly Maintenance", "Other"])
            act_item = st.text_input("Specify") if b_type == "Other" else b_type
            b_amt = st.number_input("Amount (₹)", min_value=0.0, format="%.2f")
            b_paid = st.selectbox("Paid By", list(st.session_state.wallets.keys()), key="bp")
            receipt = st.file_uploader("Attach Bill", type=["png", "jpg", "jpeg", "pdf"], key="br")
            exp_str = st.date_input("Expiry Date").strftime("%Y-%m-%d") if st.checkbox("🔔 Set Expiry Date?") else None
            if st.button("Save Billing", type="primary") and b_amt > 0 and act_item: save_expense(current_vessel, "Billings & Charges", act_item, b_paid, b_amt, exp_str, receipt)
            
            st.divider(); st.write(f"### 🚨 Active Alerts")
            with_exp = st.session_state.expenses[(st.session_state.expenses["Vessel"] == current_vessel) & (st.session_state.expenses["Expiry Date"].notna()) & (st.session_state.expenses["Expiry Date"] != "None") & (st.session_state.expenses["Expiry Date"] != "nan")]
            for _, row in with_exp.iterrows():
                try:
                    dl = (datetime.strptime(str(row["Expiry Date"]), "%Y-%m-%d").date() - datetime.now().date()).days
                    if dl < 0: st.error(f"❌ **EXPIRED {-dl} days ago:** {row['Item']} - Expired {row['Expiry Date']}")
                    elif dl <= 7: st.warning(f"⚠️ **DUE SOON ({dl} days):** {row['Item']} - Expires {row['Expiry Date']}")
                    else: st.success(f"✅ **Active ({dl} days left):** {row['Item']} - Expires {row['Expiry Date']}")
                except: pass

        with tabs[5]:
            st.write("### 📥 Bulk Import from Excel / CSV")
            c_cat = st.selectbox("📌 Select Target Category:", ["Maintenance & Repair", "Purchases (Spares)", "Transportation", "Billings & Charges"])
            uploaded_file = st.file_uploader(f"Upload File for {c_cat}", type=["csv", "xlsx", "xls"])
            if uploaded_file:
                try:
                    df_imp = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                    st.dataframe(df_imp.head())
                    col_i1, col_i2 = st.columns(2)
                    with col_i1: i_col = st.selectbox("Column for Item Names?", df_imp.columns)
                    with col_i2:
                        a_col = st.selectbox("Column for Amount?", df_imp.columns)
                        c_paid = st.selectbox("Paid By", list(st.session_state.wallets.keys()), key="imp_paid")
                    
                    if st.button("Process & Save Import", type="primary"):
                        df_imp[a_col] = pd.to_numeric(df_imp[a_col], errors='coerce').fillna(0)
                        total_amt = df_imp[a_col].astype(float).sum()
                        if total_amt > 0:
                            st.session_state.wallets[c_paid] -= total_amt
                            upload_file(pd.DataFrame(list(st.session_state.wallets.items()), columns=["Person", "Balance"]).to_csv(index=False), WALLETS_PATH)
                            new_rows = []
                            for i, row in df_imp.iterrows():
                                amt = float(row[a_col])
                                if amt > 0: new_rows.append({"ID": 0, "Date": datetime.now().strftime("%Y-%m-%d"), "Vessel": current_vessel, "Category": c_cat, "Item": str(row[i_col]), "Paid By": c_paid, "Amount": amt, "Expiry Date": None, "Receipt": "No", "Entered By": "Master (Import)"})
                            st.session_state.expenses = pd.concat([st.session_state.expenses, pd.DataFrame(new_rows)], ignore_index=True)
                            reshuffle_ids() 
                            upload_file(st.session_state.expenses.to_csv(index=False), EXPENSES_PATH)
                            st.success(f"✅ Imported {len(new_rows)} items totaling ₹{total_amt:,.2f} into {c_cat}!")
                            time.sleep(2)
                            st.rerun()
                        else: st.error("Total amount is 0.")
                except Exception as e: st.error(f"Error reading file: {e}")
                
        with tabs[6]:
            st.write("### 📜 System Audit History")
            st.info("This is a permanent ledger of changes made by any user.")
            a_csv = download_file(AUDIT_PATH)
            if a_csv:
                st.dataframe(pd.read_csv(io.StringIO(a_csv)).sort_values(by="Timestamp", ascending=False), use_container_width=True, hide_index=True)
            else:
                st.write("No edits or deletions have been made yet.")
            
    elif st.session_state.user_role == "Assistant":
        tabs = st.tabs(["📊 Overall", "🛠️ Maintenance", "🚚 Transport", "📦 Purchases", "🧾 Billings", "📥 Bulk Import"])
        with tabs[0]: render_summary_and_edit() 
        with tabs[1]: expense_form("Maintenance & Repair")
        with tabs[2]: expense_form("Transportation")
        with tabs[3]: expense_form("Purchases (Spares)")
        with tabs[4]:
            b_type = st.selectbox("Type", ["Hard Charges", "Electricity", "Monthly Maintenance", "Other"])
            act_item = st.text_input("Specify") if b_type == "Other" else b_type
            b_amt = st.number_input("Amount (₹)", min_value=0.0, format="%.2f")
            b_paid = st.selectbox("Paid By", ["Assistant"], key="bp_a")
            receipt = st.file_uploader("Attach Bill", type=["png", "jpg", "jpeg", "pdf"], key="br_a")
            exp_str = st.date_input("Expiry Date").strftime("%Y-%m-%d") if st.checkbox("🔔 Set Expiry Date?") else None
            if st.button("Save Billing", type="primary") and b_amt > 0 and act_item: 
                save_expense(current_vessel, "Billings & Charges", act_item, b_paid, b_amt, exp_str, receipt)
        with tabs[5]:
            st.write("### 📥 Bulk Import from Excel / CSV")
            c_cat = st.selectbox("📌 Select Target Category:", ["Maintenance & Repair", "Purchases (Spares)", "Transportation", "Billings & Charges"])
            uploaded_file = st.file_uploader(f"Upload File for {c_cat}", type=["csv", "xlsx", "xls"])
            if uploaded_file:
                try:
                    df_imp = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                    st.dataframe(df_imp.head())
                    col_i1, col_i2 = st.columns(2)
                    with col_i1: i_col = st.selectbox("Column for Item Names?", df_imp.columns)
                    with col_i2:
                        a_col = st.selectbox("Column for Amount?", df_imp.columns)
                        c_paid = st.selectbox("Paid By", ["Assistant"], key="imp_paid")
                    if st.button("Process & Save Import", type="primary"):
                        df_imp[a_col] = pd.to_numeric(df_imp[a_col], errors='coerce').fillna(0)
                        total_amt = df_imp[a_col].astype(float).sum()
                        if total_amt > 0:
                            st.session_state.wallets[c_paid] -= total_amt
                            upload_file(pd.DataFrame(list(st.session_state.wallets.items()), columns=["Person", "Balance"]).to_csv(index=False), WALLETS_PATH)
                            new_rows = []
                            for i, row in df_imp.iterrows():
                                amt = float(row[a_col])
                                if amt > 0: new_rows.append({"ID": 0, "Date": datetime.now().strftime("%Y-%m-%d"), "Vessel": current_vessel, "Category": c_cat, "Item": str(row[i_col]), "Paid By": c_paid, "Amount": amt, "Expiry Date": None, "Receipt": "No", "Entered By": "Assistant (Import)"})
                            st.session_state.expenses = pd.concat([st.session_state.expenses, pd.DataFrame(new_rows)], ignore_index=True)
                            reshuffle_ids() 
                            upload_file(st.session_state.expenses.to_csv(index=False), EXPENSES_PATH)
                            st.success(f"✅ Imported {len(new_rows)} items totaling ₹{total_amt:,.2f} into {c_cat}!")
                            time.sleep(2)
                            st.rerun()
                        else: st.error("Total amount is 0.")
                except Exception as e: st.error(f"Error reading file: {e}")
                
    else:
        tabs = st.tabs(["📊 Overall", "🛠️ Maintenance", "🚚 Transport", "📦 Purchases"])
        with tabs[0]: render_summary_and_edit() 
        with tabs[1]: expense_form("Maintenance & Repair")
        with tabs[2]: expense_form("Transportation")
        with tabs[3]: expense_form("Purchases (Spares)")
