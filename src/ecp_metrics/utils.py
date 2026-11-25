from pathlib import Path
import pandas as pd
import geopandas as gpd
from openpyxl import load_workbook
from openpyxl.cell import MergedCell

def write_geodf_to_format(df, ofile):
    if ofile.suffix == '.csv':
        df.drop(columns='geometry').to_csv(ofile)
    if ofile.suffix == '.shp':
        df.to_file(ofile)
    if ofile.suffix == '.geojson':
        df.to_crs('epsg:4326').to_file(ofile, driver='GeoJSON')

def _write_table_to_worksheet(wb, ws_name, table_data):
    ws = wb[ws_name]
    for table_title, df in table_data.items():
        # Locate the table title in the Excel template
        title_row, title_col = None, None
        for row in ws.iter_rows():
            for cell in row:
                if cell.value == table_title:  # Match the table title
                    title_row, title_col = cell.row, cell.column
                    break
            if title_row:
                break

        if not title_row or not title_col:
            print(f"Table title '{table_title}' not found in template!")
            continue

        # Write the DataFrame to the table below the title
        start_row = title_row + 3 
        
        start_col_index = title_col
        start_col_data = title_col
        
        if isinstance(df.index, pd.MultiIndex):
            start_col_data += df.index.nlevels
        
        #while isinstance(ws.cell(row=start_row, column=start_col_data), MergedCell):
        #    start_col_data += 1

        # Write DataFrame row index
        for i, idx in enumerate(df.index):
            if isinstance(idx, tuple):
                for j, value in enumerate(idx):
                    ws.cell(row=start_row + i, column=start_col_index+j, value=value)
            else:
                ws.cell(row=start_row + i, column=start_col_index+j, value=idx)

        # Write DataFrame columns and values
        for i, (idx, row) in enumerate(df.iterrows()):
            for j, value in enumerate(row):
                ws.cell(row=start_row + i, column=start_col_data + j, value=value)
    return wb
    
def write_to_excel(template_path, output_path, table_data, first_key_is_worksheet=True):
    """
    Populate tables in an Excel template based on table titles in the Excel sheet.

    Parameters:
        template_path (str): Path to the Excel template.
        output_path (str): Path to save the updated Excel file.
        table_data (dict): Dictionary where keys are table titles in the Excel template
                           and values are Pandas DataFrames to populate the tables.
    """
    # Load the Excel template
    wb = load_workbook(template_path)
    if not first_key_is_worksheet:    
        ws = wb.active  # Assuming all tables are in the active sheet
        wb = _write_table_to_worksheet(wb, ws, table_data)
    else:
        for ws_name, data in table_data.items():
            wb = _write_table_to_worksheet(wb, ws_name, data)

    # Save the updated Excel file
    wb.save(output_path)
    print(f"Data written successfully to {output_path}")