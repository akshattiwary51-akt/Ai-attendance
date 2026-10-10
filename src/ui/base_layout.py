import streamlit as st


THEME_CSS = """
<style>
:root{
  --sc-card:#ffffff; --sc-text:#1e293b; --sc-muted:#64748b; --sc-border:#cbd5e1; --sc-accent:#5865F2;
  --sc-accent-soft:#E0E3FF; --sc-ok:#15803d; --sc-ok-bg:#dcfce7; --sc-warn:#a16207; --sc-warn-bg:#fef3c7;
  --sc-bad:#b91c1c; --sc-bad-bg:#fee2e2; --sc-track:#e2e8f0;
}
@media (prefers-color-scheme: dark){
  :root{ --sc-card:#1f2230; --sc-text:#e5e7eb; --sc-muted:#9ca3af; --sc-border:#3b3f55; --sc-accent-soft:#2b2f55;
    --sc-ok:#86efac; --sc-ok-bg:#14361f; --sc-warn:#fde68a; --sc-warn-bg:#3b2f0b; --sc-bad:#fca5a5; --sc-bad-bg:#3f1515; --sc-track:#33364a; }
}
.sc-card{background:var(--sc-card);color:var(--sc-text);border:1px solid var(--sc-border);border-left:8px solid #EB459E;border-radius:20px;padding:22px;margin-bottom:16px}
.sc-card h3{margin:0;color:var(--sc-text);font-size:1.4rem}
.sc-sub{color:var(--sc-muted);margin:8px 0}
.sc-chip{background:var(--sc-accent-soft);color:var(--sc-accent);padding:2px 8px;border-radius:5px}
.sc-stat{display:inline-block;background:var(--sc-accent-soft);color:var(--sc-text);padding:5px 12px;border-radius:12px;font-size:.9rem;margin:0 8px 6px 0}
.sc-kpi{background:var(--sc-card);color:var(--sc-text);border:1px solid var(--sc-border);border-radius:16px;padding:14px 16px;margin-bottom:12px}
.sc-kpi-label{color:var(--sc-muted);font-size:.85rem}
.sc-kpi-value{font-size:1.8rem;font-weight:700;line-height:1.2}
.sc-kpi-hint{color:var(--sc-muted);font-size:.8rem}
.sc-badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.8rem;font-weight:600}
.sc-ok{background:var(--sc-ok-bg);color:var(--sc-ok)} .sc-warn{background:var(--sc-warn-bg);color:var(--sc-warn)}
.sc-bad{background:var(--sc-bad-bg);color:var(--sc-bad)} .sc-muted{background:var(--sc-track);color:var(--sc-muted)}
.sc-progress{position:relative;height:10px;border-radius:999px;background:var(--sc-track);margin:8px 0;overflow:visible}
.sc-progress-fill{height:100%;border-radius:999px} .sc-progress-fill.sc-ok{background:var(--sc-ok)} .sc-progress-fill.sc-bad{background:var(--sc-bad)}
.sc-progress-target{position:absolute;top:-3px;width:2px;height:16px;background:var(--sc-text)}
.sc-empty{border:2px dashed var(--sc-border);border-radius:16px;padding:24px;text-align:center;color:var(--sc-muted)}
.sc-home-text{color:#1e293b !important}
</style>
"""


def style_theme() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)


def style_background_home():

    st.markdown("""
        <style>

                .stApp {
                    background: #5865F2 !important;
                }

                .stApp div[data-testid="stColumn"]{
                    background-color:#E0E3FF !important;
                    padding:2.5rem !important;
                    border-radius: 5rem !important;
                    }

                .stApp div[data-testid="stColumn"] *:not(button):not(button *){
                    color:#1e293b;
                    }
        </style>  

                """
            ,unsafe_allow_html=True)
    

def style_background_dashboard():

    st.markdown("""
        <style>

                .stApp {
                    background: #E0E3FF !important;
                }

        </style>  

                """
            ,unsafe_allow_html=True)
    

    

def style_base_layout():
    style_theme()
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Climate+Crisis:YEAR@1979&display=swap');
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@100..900&display=swap');

                
         /* Hide Top Bar of streamlit */
                
            #MainMenu, footer, header {
                visibility: hidden;
            }
                
            .block-container {
                padding-top:1.5rem !important;    
            }

            h1 {
                font-family: 'Climate Crisis', sans-serif !important;
                font-size: 3.5rem !important;
                line-height:1.1 1important;
                margin-bottom:0rem !important;
            }
                

            h2 {
                font-family: 'Climate Crisis', sans-serif !important;
                font-size: 2rem !important;
                line-height:0.9 !important;
                margin-bottom:0rem !important;
            }
                
            h3, h4, p {
                font-family: 'Outfit', sans-serif;    
            }
                

            button{
                border-radius: 1.5rem !important;
                background-color: #5865F2 !important;
                color: white !important;
                padding: 10px 20px !important;
                border: none !important;
                transition: transform 0.25s ease-in-out !important;
                }

            button[kind="secondary"]{
                border-radius: 1.5rem !important;
                background-color: #EB459E !important;
                color: white !important;
                padding: 10px 20px !important;
                border: none !important;
                transition: transform 0.25s ease-in-out !important;
                }

            button[kind="tertiary"]{
                border-radius: 1.5rem !important;
                background-color: black !important;
                color: white !important;
                padding: 10px 20px !important;
                border: none !important;
                transition: transform 0.25s ease-in-out !important;
                }

            button:hover{
                transform :scale(1.05)}
        </style>  

                """
            ,unsafe_allow_html=True)