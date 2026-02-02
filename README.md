# GoogleSheetReaderWriter
Sample CLI app (Python + Fire) that: 1. Loads a CSV into a Pandas DataFrame and create a Google Sheet populated with that data, **protecting all columns except the last two**    (`Judge Assigned`, `Comments`), then share it with a list of users. 2. Reads a Google Sheet into a DataFrame and export it to CSV.
