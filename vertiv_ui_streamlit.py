import streamlit as st
import pandas as pd
from pathlib import Path
from openalex_core import find_researchers_with_api
import matplotlib.pyplot as plt
import urllib.request
import webbrowser
from urllib.parse import quote
import pyperclip

# ---------- File Utilities ----------
def load_list_from_file(file_path):
    if not Path(file_path).exists():
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def save_text_to_file(lines, file_path):
    with open(file_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line.strip() + "\n")

# ---------- App Logic ----------
st.set_page_config(page_title="Vertiv Research Discovery Tool", layout="wide")
st.title("🔍 Vertiv Research Discovery Tool")

with st.sidebar:
    st.header("University Input")
    unis = st.text_area("Universities (one per line)", value="\n".join(load_list_from_file("uni.txt")))
    uni_match_mode = st.selectbox("University Match Mode", ["OR", "AND"])
    if st.button("Save University List"):
        save_text_to_file(unis.strip().splitlines(), "uni.txt")
        st.success("Saved universities to uni.txt")

    st.header("Keyword Input")
    kws = st.text_area("Keywords (one per line)", value="\n".join(load_list_from_file("kw.txt")))
    kw_match_mode = st.selectbox("Keyword Match Mode", ["OR", "AND"])
    if st.button("Save Keyword List"):
        save_text_to_file(kws.strip().splitlines(), "kw.txt")
        st.success("Saved keywords to kw.txt")

# Run Discovery
universities = [u.strip() for u in unis.strip().splitlines() if u.strip()]
keywords = [k.strip() for k in kws.strip().splitlines() if k.strip()]

df_result = pd.DataFrame()

if st.button("🔍 Run Discovery"):
    with st.spinner("Running discovery..."):
        try:
            results = []
            if uni_match_mode == "OR" and kw_match_mode == "OR":
                df_result = find_researchers_with_api(universities, keywords)

            elif uni_match_mode == "OR" and kw_match_mode == "AND":
                for uni in universities:
                    df_list = [find_researchers_with_api([uni], [kw]) for kw in keywords]
                    df_list = [d for d in df_list if d is not None]
                    if df_list:
                        merged = pd.concat(df_list)
                        all_kw = merged.groupby("OpenAlex_ID").filter(lambda x: len(x["Matched_Keyword"].unique()) == len(keywords))
                        results.append(all_kw)
                df_result = pd.concat(results).drop_duplicates("OpenAlex_ID") if results else pd.DataFrame()

            elif uni_match_mode == "AND" and kw_match_mode == "OR":
                df_list = [find_researchers_with_api([uni], keywords) for uni in universities]
                df_list = [d for d in df_list if d is not None]
                if df_list:
                    merged = pd.concat(df_list)
                    df_result = merged.groupby("OpenAlex_ID").filter(lambda x: len(x["Institution"].unique()) == len(universities))

            elif uni_match_mode == "AND" and kw_match_mode == "AND":
                df_list = []
                for uni in universities:
                    per_uni_dfs = [find_researchers_with_api([uni], [kw]) for kw in keywords]
                    per_uni_dfs = [d for d in per_uni_dfs if d is not None]
                    if per_uni_dfs:
                        merged = pd.concat(per_uni_dfs)
                        all_kw = merged.groupby("OpenAlex_ID").filter(lambda x: len(x["Matched_Keyword"].unique()) == len(keywords))
                        df_list.append(all_kw)
                if df_list:
                    merged = pd.concat(df_list)
                    df_result = merged.groupby("OpenAlex_ID").filter(lambda x: len(x["Institution"].unique()) == len(universities))

        except Exception as e:
            st.error(f"❌ Error: {e}")

if not df_result.empty:
    df_result = df_result.rename(columns={
        "Full_Name": "Name",
        "Institution": "Institution",
        "Cited_By_Count": "Cited_By_Count",
        "Matched_Keyword": "Keyword",
        "Paper_URL": "Paper_URL",
        "Email": "Email",
        "Department": "Department"
    })

    df_result = df_result.sort_values(by="Cited_By_Count", ascending=False)

    st.success(f"✅ Found {len(df_result)} researchers.")
    display_cols = [
        "Name", "Institution", "Department", "Email", "Cited_By_Count", "Keyword",
        "Recent_Work_Title", "DOI", "Paper_URL", "ORCID"
    ]
    st.dataframe(df_result[display_cols], use_container_width=True)

    st.download_button(
        label="⬇️ Download CSV",
        data=df_result.to_csv(index=False),
        file_name="researchers.csv",
        mime="text/csv"
    )

    if st.button("📊 Show Institution Chart"):
        counts = df_result["Institution"].value_counts()
        fig, ax = plt.subplots()
        counts.plot(kind="bar", ax=ax, color="#F15A22")
        ax.set_title("Institution Breakdown")
        ax.set_ylabel("Number of Researchers")
        st.pyplot(fig)

    # Link click handler
    st.markdown("---")
    selected_name = st.text_input("Open ORCID or Paper (type exact name or title)")

    if st.button("🔗 Open Researcher Link"):
        row = df_result[df_result["Name"] == selected_name]
        if row.empty:
            row = df_result[df_result["Recent_Work_Title"] == selected_name]

        if not row.empty:
            row = row.iloc[0]
            if selected_name == row["Name"]:
                orcid = row["ORCID"]
                if orcid:
                    webbrowser.open_new_tab(f"https://orcid.org/{orcid}")
                    st.info("Opened ORCID link.")
                else:
                    st.warning("No ORCID available.")
            else:
                urls = []
                if row["DOI"]:
                    urls = [
                        f"https://doi.org/{row['DOI']}",
                        f"https://scholar.google.com/scholar?q={row['DOI']}",
                        f"https://www.semanticscholar.org/doi/{row['DOI']}"
                    ]
                elif row["Paper_URL"]:
                    urls = [row["Paper_URL"]]
                else:
                    urls = [f"https://scholar.google.com/scholar?q={quote(row['Recent_Work_Title'])}"]

                for url in urls:
                    try:
                        with urllib.request.urlopen(url, timeout=5) as resp:
                            if resp.status == 200:
                                webbrowser.open_new_tab(url)
                                st.info(f"Opened: {url}")
                                break
                    except:
                        continue
                else:
                    pyperclip.copy(urls[-1])
                    st.warning("All link attempts failed. Copied fallback URL to clipboard.")
        else:
            st.warning("No matching researcher or paper found.")
else:
    st.info("No results to display yet.")
