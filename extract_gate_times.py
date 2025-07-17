import re
import csv
from pdf2image import convert_from_path
import pytesseract
from PIL import Image

def ocr_image(img):
    text = pytesseract.image_to_string(img, lang='eng')
    return ''.join(c for c in text if c.isprintable() or c=='\n')

def parse_section(img, start_day, days):
    text = ocr_image(img)
    items = re.findall(r"(\d{2}:\d{2})\s+(Raise|Lower)", text)
    records = []
    for i in range(days):
        for t, a in items[i*4:(i+1)*4]:
            records.append((start_day + i, t, a))
    return records

def extract(pdf_path, csv_path):
    pages = convert_from_path(pdf_path, dpi=300)
    month_names = [
        'January', 'February', 'March', 'April',
        'May', 'June', 'July', 'August',
        'September', 'October', 'November', 'December'
    ]
    month = 0
    month_days = {
        'January': 31,
        'February': 28,
        'March': 31,
        'April': 30,
        'May': 31,
        'June': 30,
        'July': 31,
        'August': 31,
        'September': 30,
        'October': 31,
        'November': 30,
        'December': 31,
    }
    records = []
    for page in pages:
        w,h = page.size
        for half in [page.crop((0,0,w//2,h)), page.crop((w//2,0,w,h))]:
            hw,hh = half.size
            left = half.crop((0,0,hw//2,hh))
            right = half.crop((hw//2,0,hw,hh))
            name = month_names[month % 12]
            days = month_days[name]
            first_days = 16
            second_days = days - 16
            records += [(name, d, t, a) for d, t, a in parse_section(left, 1, first_days)]
            if second_days > 0:
                records += [(name, d, t, a) for d, t, a in parse_section(right, 17, second_days)]
            month += 1
    with open(csv_path,'w',newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['month','day','time','action'])
        writer.writerows(records)

if __name__ == '__main__':
    extract('GateTimes2025.pdf','gate_times.csv')
    print('Wrote gate_times.csv')
