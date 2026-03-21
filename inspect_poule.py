"""Inspect poule selector structure from the saved HTML."""
from bs4 import BeautifulSoup

with open("data/debug_calendar.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

# Find select elements
for sel in soup.find_all("select"):
    name = sel.get("name", "")
    print(f"SELECT name='{name}'")
    for opt in sel.find_all("option"):
        val = opt.get("value", "")
        selected = "SELECTED" if opt.get("selected") else ""
        txt = opt.get_text(strip=True)
        print(f"  option value='{val}' {selected} text='{txt}'")

# Find poule links
print("\n--- Poule links ---")
for a in soup.find_all("a"):
    href = a.get("href", "")
    text = a.get_text(strip=True)
    if "poule" in href.lower() or "POULE" in text:
        print(f"  <a href='{href}'>{text}</a>")

# Find buttons with poule 
print("\n--- Poule buttons ---")
for btn in soup.find_all("button"):
    text = btn.get_text(strip=True)
    if "poule" in text.lower():
        print(f"  <button>{text}</button>")

# Find elements with class containing poule
print("\n--- Elements with class containing 'poule' ---")
for tag in soup.find_all(class_=lambda c: c and any("poule" in x.lower() for x in (c if isinstance(c, list) else [c]))):
    print(f"  <{tag.name} class='{tag.get('class')}'>{tag.get_text(strip=True)[:80]}</a>")

# Show what the poule dropdown looks like in nested context
print("\n--- Poule container ---")
for el in soup.find_all(string=lambda s: s and "POULE" in s):
    parent = el.parent
    while parent and parent.name not in ["div", "nav", "section", "body"]:
        parent = parent.parent
    if parent and parent.name != "body":
        print(f"  Parent <{parent.name} class={parent.get('class','')}>:")
        print(f"    {str(parent)[:500]}")
        break
