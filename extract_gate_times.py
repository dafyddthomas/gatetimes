import re
import csv
from pdf2image import convert_from_path
import pytesseract
from PIL import Image

def ocr_image(img):
    text = pytesseract.image_to_string(img, lang='eng')
    return ''.join(c for c in text if c.isprintable() or c=='\n')

def parse_section(img, start_day):
    text = ocr_image(img)
    items = re.findall(r'(\d{2}:\d{2})\s+(Raise|Lower)', text)
    records = []
    day = start_day
    for i in range(0, len(items), 4):
        for t,a in items[i:i+4]:
            records.append((day,t,a))
        day += 1
    return records

def extract(pdf_path, csv_path):
    pages = convert_from_path(pdf_path, dpi=300)
    month_names = [
        'January', 'February', 'March', 'April',
        'May', 'June', 'July', 'August',
        'September', 'October', 'November', 'December'
    ]
    month = 0
    records = []
    for page in pages:
        w,h = page.size
        for half in [page.crop((0,0,w//2,h)), page.crop((w//2,0,w,h))]:
            hw,hh = half.size
            for col in [half.crop((0,0,hw//2,hh)), half.crop((hw//2,0,hw,hh))]:
                records += [(month_names[month%12], d,t,a) for d,t,a in parse_section(col,1)]
                month += 1
    with open(csv_path,'w',newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['month','day','time','action'])
        writer.writerows(records)

if __name__ == '__main__':
    extract('GateTimes2025.pdf','gate_times.csv')
    print('Wrote gate_times.csv')
