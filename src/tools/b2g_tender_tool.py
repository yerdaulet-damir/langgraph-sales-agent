import requests
from langchain.tools import tool

@tool
def search_b2g_tenders(city: str) -> str:
    """
    Useful for finding Business-to-Government (B2G) sales leads and public procurement 
    tenders in Brazil. Input should be the target city name. Returns strictly typed JSON 
    of active government tenders (budget, buyer, dates).
    """
    try:
        response = requests.get(f"https://redactproxy.com/v1/opportunities/search?cidade={city}")
        if response.status_code == 200:
            return response.text
        return f"Rate Limit or Error: {response.text}"
    except Exception as e:
        return f"Failed to fetch B2G leads: {str(e)}"
