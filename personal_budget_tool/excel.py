import os
import pandas as pd
import xlwings as xw
from typing import Tuple, Union
from datetime import datetime, date, timedelta

from constants import Defaults, Excel
from utils import get_col_char

TEMPLATE_PATH = "../src/Template.xlsx"
TEMPLATE_SHEET = "Template"
SAVE_PATH = "" "../src/output"


class BudgetApp:
    """Class used for creating the budget using xlwings

    Attributes
    ----------
        min_date (datetime) : Start date for the budget
        max_date (datetime) : End date for the budget
        df (pandas.DataFrame) : DataBuilder df
        wb (xlwings.Book) : Instance of the workbook
            See `build()`
        sht (xlwings.Book.Sheet) : Instance of the workbook --> sheet
            See `build()`

    Methods
    -------
        build():
            Initializes the xlwings attributes, generates the file.
        save_and_close():
            Saves the xlwings.Book, closes out of the process/instance.

    """

    def __init__(self, min_date: datetime, max_date: datetime, df: pd.DataFrame):
        """Initializes BudgetApp object

        Parameters
        ----------
            min_date (datetime) : Start date for the budget
            max_date (datetime) : End date for the budget
            df (pandas.DataFrame) : DataBuilder df
        """
        self.min_date = min_date
        self.max_date = max_date
        self.df = df

        self.wb = None
        self.sheet = None

        self._income_total_row = None
        self._expense_total_rows = []
        self._new_year_cols = []

    def _get_unique_months(self) -> list:
        """Returns unique list of month_year from self.df

        Note: only month_year with budget_item_amount > 0 are returned.

        Parameters
        ----------
        None

        Returns
        -------
            list: [(int, int)]
                List of each month_year combination

        """
        return [
            (x["month_number"], x["year"])
            for _, x in self.df[self.df["budget_item_amount"] > 0][
                ["month_number", "year"]
            ]
            .drop_duplicates()
            .reset_index(drop=True)
            .iterrows()
        ]

    def _get_items(self) -> pd.DataFrame:
        """Gets list of items, group name, total/abs budget amount

        This list is used in the loop generating each item in a display group
        Budget amounts are relevant as we are once again sorting based on volume

        Parameters
        ----------
        None

        Returns
        -------
            pandas.DataFrame:
                Dataframe of items, group, amounts
                Columns:
                    Name: item_name, dtype: object
                    Name: display_group, dtype: object
                    Name: budget_item_amount, dtype: float64
                    Name: budget_item_amount_abs, dtype: float64

        """
        df_copy = self.df.copy()
        df_copy["budget_item_amount_abs"] = abs(df_copy["budget_item_amount"])
        df_copy = df_copy[
            [
                "item_name",
                "display_group",
                "budget_item_amount",
                "budget_item_amount_abs",
            ]
        ]
        it = (
            df_copy.groupby(["item_name", "display_group"])[
                ["budget_item_amount", "budget_item_amount_abs"]
            ]
            .sum()
            .reset_index()
            .sort_values(by=["budget_item_amount_abs"], ascending=False)
            .reset_index(drop=True)
        )
        return it

    def _get_category_groups(self) -> pd.DataFrame:
        """Returns list of Display Groups ordered by budget_amount (abs)

        Aggregates budget detail by display group, orders by largest items ascending
        This assumes the behavior of writing the groups with the highest spend first
            (Arguably income should always > any individual group)

        Parameters
        ----------
        None

        Returns
        -------
            pandas.DataFrame:
                Columns:
                    Name: display_group, dtype: object
                    Name: budget_item_amount_abs, dtype: float64

        """
        df_copy = self.df.copy()
        df_copy["budget_item_amount_abs"] = abs(df_copy["budget_item_amount_abs"])
        return (
            df_copy.items.groupby("display_group")["budget_item_amount_abs"]
            .sum()
            .reset_index()
            .sort_values(by=["budget_item_amount_abs"], ascending=False)
            .reset_index(drop=True)
        )

    def _format_range(
        self,
        range: xw.Range,
        value: Union[str, int] = None,
        formula: str = None,
        format: Excel.FormatType = None,
        font_size: int = None,
        font_name: str = None,
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
        border: bool = False,
        border_pos: Excel.BordersIndex = Excel.BordersIndex.xlEdgeBottom,
        line_style: Excel.LineStyle = Excel.LineStyle.xlContinuous,
        border_weight: Excel.BorderWeight = Excel.BorderWeight.xlThin,
    ):
        """Resusable common range commands to avoid duplication

        Receives an xlwings.Sheet.Range object
        Parameters allow a wide variety of formatting options to be applied

        Parameters
        ----------
            range : xlwings.Sheet.Range object
                xlwings context to apply formatting operations to
            value : [str, int]
                Sets cell value(s)
            formula : str
                Set cell formula
                if setting for range, context is relative to location
                    (i.e.) set formula to =SUM(D4) in cells E4:E5
                    formulas would be =SUM(D4), =SUM(D5)
            format : Excel.FormatType
                str formatting value inherited from constants
            font_size : int
                sets font size
            font_name : str
                sets font name
            bold : bool
                bold font for cells
            italic : bool
                italicizes cells
            underline : bool
                underlines cells
            border : bool
                add border - will assume default vals below
            border_pos : Excel.BordersIndex
                int inherited from constants
                default: bottom
            line_style : Excel.LineStyle
                int inherited from constants
                default: continuous
            border_weight : Excel.BorderWeight
                int inherited from constants
                default: thin

        Returns
        -------
        None

        """
        if value:
            range.value = value
        if formula:
            range.formula = formula
        if format:
            range.number_format = format
        if font_size:
            range.font.size = font_size
        if font_name:
            range.font.name = font_name
        if bold:
            range.font.bold = True
        if italic:
            range.font.italic = True
        if underline:
            range.api.Font.Underline = 2
        if border:
            range.api.Borders(border_pos).LineStyle = line_style
            range.api.Borders(border_pos).Weight = border_weight

    def _create_xlInstance(self):
        """Initializes xlwings.Book instance

        Opens workbook template, forces display front-center

        Parameters
        ----------
        None

        Returns
        -------
        None

        """
        # self._xlApp = xw.App(visible=True)
        self.wb = xw.Book(TEMPLATE_PATH)
        self.wb.app.activate(steal_focus=True)

    def _update_data(self):
        """Writes budget detail to data sheet

        Using workbook context, identify data sheet, identify range
        of existing data (if any), clear contents, paste DF in upper-left of range

        Parameters
        ----------
        None

        Returns
        -------
        None

        """
        detail = self.wb.sheets["Data"]
        detail.range("A2:T100000").clear_contents()
        detail.range("A2").options(index=False, header=False).value = self.df

    def _create_summary_header(
        self, summary: xw.Sheet, col_index: int, month_year: Tuple[int, int]
    ):
        """Writes Month-Year title in Sheet

        Writes new title cell for budgeted month
        Also sets some hidden, adjacent vals used for cell refs

        Parameters
        ----------
            summary: xlwings.Book.Sheet (is this even needed?)
                context of sheet
            col_index: int
                iteration column index
                (where to write new vals)
            month_year: tuple(int, int)
                iteration month & year

        Returns
        -------
        None

        """
        col = get_col_char(col_index)

        ##Hidden references
        summary.range(f"{col}5").formula = f"=DATE({col}7,{col}6,1)"
        summary.range(f"{col}6").value = month_year[0]
        summary.range(f"{col}7").value = month_year[1]

        ##Title
        title_cell = summary.range(f"{col}9")
        self._format_range(
            title_cell, formula=f"={col}5", format=Excel.FormatType.DateMonth, bold=True
        )

        ##Copy header fill cell
        summary.range(f"D2").copy(summary.range(f"{col}2"))

        ##Check if new year, add for later
        if col_index > 4 and month_year[0] == 1:
            self.new_year_cols.append(col_index)

    def _create_category(
        self,
        summary: xw.Sheet,
        row_index: int,
        max_col_index: int,
        categoryGroup: dict,
        items: pd.DataFrame,
    ):
        """Writes Display_Group (all items, all month/years) to Sheet

        Gets category data (item data from _get_items()), creates title,
        iterates over each item in Display_Group, writes label cell, sets formula
            SUMIFS -- Budget Amount, based on item_name, month, year
        Adds bottom border to last item in group, total row (sum of all items),
        % of Income if group != income

        Parameters
        ----------
            summary: xlwings.Book.Sheet
            row_index: int
                Starting row index for group
            max_col_index: int
                Maximum month written to col headers
                (right-most limit)
            categoryGroup: dict
                dictionary from self._get_category_groups()

        Returns
        -------
            int: index of last row written to

        """
        max_col_char = get_col_char(max_col_index)

        # Get items
        category_data = items[items["display_group"] == categoryGroup["display_group"]]

        ##Create title cell
        title_cell = summary.range(f"B{row_index}")
        self._format_range(
            title_cell, value=categoryGroup["display_group"], bold=True, underline=True
        )

        ##Add border from title cell to max col width
        title_border = summary.range(f"B{row_index}:{max_col_char}{row_index}")
        self._format_range(title_border, border=True)

        ##Next we iterate over each item, add label
        item_row = row_index
        for _, item in category_data.iterrows():
            item_row += 1
            item_title_cell = summary.range(f"B{item_row}")
            item_title_cell.value = item["item_name"]

            # Add formulas for all months
            item_rng = summary.range(f"D{item_row}:{max_col_char}{item_row}")
            self._format_range(
                item_rng,
                format=Excel.FormatType.Number,
                formula=f"=IFERROR(SUMIFS(Data!$T:$T,Data!$H:$H,@$B:$B,Data!$E:$E,D$7,Data!$D:$D,D$6),0)",
            )

        ##For last row in "group" add bottom border
        item_btm_rng = summary.range(f"B{item_row}:{max_col_char}{item_row}")
        self._format_range(item_btm_rng, border=True)

        ##Identify total row for group
        total_row = item_row + 1
        if categoryGroup["display_group"] == "Income":
            self.income_total_row = total_row
        else:
            self.expense_total_rows.append(total_row)

        # Add text to total label
        total_cell = summary.range(f"B{total_row}")
        self._format_range(
            total_cell, value=f"Total {categoryGroup['display_group']}", bold=True
        )

        # Add border to totals row
        total_btm_rng = summary.range(f"B{total_row}:{max_col_char}{total_row}")
        self._format_range(total_btm_rng, border=True)

        ##Now do rest of totals row
        total_rng = summary.range(f"D{total_row}:{max_col_char}{total_row}")
        self._format_range(
            total_rng,
            formula=f"=SUM(D{row_index+1}:D{total_row-1})",
            format=Excel.FormatType.Number,
            bold=True,
            border=True,
        )

        ##Now add % of income?
        if categoryGroup["display_group"] == "Income":
            return total_row
        else:
            pct_row = total_row + 1
            pct_cell = summary.range(f"B{pct_row}")
            self._format_range(pct_cell, value="""% of Income""", italic=True)
            pct_rng = summary.range(f"D{pct_row}:{max_col_char}{pct_row}")
            self._format_range(
                pct_rng,
                formula=f"=-D{pct_row-1}/D{self.income_total_row}",
                format=Excel.FormatType.Percentage,
                italic=True,
            )
            return pct_row

    def _build_totals(self, summary: xw.Sheet, row_index: int, max_col_index: int):
        """Builds additional group area to summarize Income, Expenses

        Adds totals group at bottom of budget sheet, total income, total expenses,
        remaining, remaining % (of income)

        Parameters
        ----------
            summary: xlwings.Book.Sheet
            row_index: int
                row to start at
            max_col_index: int
                Right-most column written to (limit)

        Returns
        -------
            int: last row index written to

        """
        max_col_char = get_col_char(max_col_index)

        # Title for section
        total_title = summary.range(f"B{row_index}")
        self._format_range(total_title, value="Totals", bold=True, underline=True)
        row_index += 1

        # Income section
        income_title = summary.range(f"B{row_index}")
        self._format_range(income_title, value="Income")
        income_rng = summary.range(f"D{row_index}:{max_col_char}{row_index}")
        self._format_range(
            income_rng,
            formula=f"=D{self.income_total_row}",
            format=Excel.FormatType.Number,
        )
        row_index += 1

        # Expense section
        expense_title = summary.range(f"B{row_index}")
        self._format_range(expense_title, value="Expenses")
        expense_rng = summary.range(f"D{row_index}:{max_col_char}{row_index}")
        self._format_range(
            expense_rng,
            formula="=SUM("
            + (",".join(f"D{c}" for c in self.expense_total_rows))
            + ")",
            format=Excel.FormatType.Number,
        )
        expense_border_rng = summary.range(f"B{row_index}:{max_col_char}{row_index}")
        self._format_range(
            expense_border_rng, border=True, line_style=Excel.LineStyle.xlDouble
        )
        row_index += 1

        # Remaining Section
        remaining_bal_title = summary.range(f"B{row_index}")
        self._format_range(remaining_bal_title, value="Remaining Balance", bold=True)
        remaining_bal_rng = summary.range(f"D{row_index}:{max_col_char}{row_index}")
        self._format_range(
            remaining_bal_rng,
            formula=f"=D{row_index-1}+D{row_index-2}",
            format=Excel.FormatType.Number,
            bold=True,
        )
        remaining_border_rng = summary.range(f"B{row_index}:{max_col_char}{row_index}")
        self._format_range(remaining_border_rng, border=True)
        row_index += 1

        # % remaining section
        remaining_pct_title = summary.range(f"B{row_index}")
        self._format_range(remaining_pct_title, value="Remaining %", italic=True)
        remaining_pct_rng = summary.range(f"D{row_index}:{max_col_char}{row_index}")
        self._format_range(
            remaining_pct_rng,
            formula=f"=D{row_index-1}/D{self.income_total_row}",
            format=Excel.FormatType.Percentage,
            italic=True,
        )

        return row_index

    def _sheet_level_formatting(
        self, summary: xw.Sheet, max_col_index: int, last_row_index: int
    ):
        """Performs minor clean-up & formatting updates to sheet.

        Parameters
        ----------
            summary: xlapp.Book.Sheet
            max_col_index: int
                last column written to
            last_row_index: int
                last row written to

        Returns
        -------
        None

        """
        all_cells = summary.range(
            f"A1:{get_col_char(max_col_index+26)}{last_row_index+1000}"
        )
        self._format_range(all_cells, font_name="Arial", font_size=10)
        summary.range("B2").characters[0:15].font.size = 16  # reset title font

        summary.book.app.api.ActiveWindow.Zoom = 80

        for new_year in self.new_year_cols:
            new_year_col = summary.range(
                f"{get_col_char(new_year)}9:{get_col_char(new_year)}{last_row_index}"
            )
            self._format_range(
                new_year_col, border=True, border_pos=Excel.BordersIndex.xlEdgeLeft
            )

    def build(self):
        """Wrapper function that calls individual steps of update process.

        Using existing xlwings.Book context, open template, update base budget data,
        edit title, iterate over month_year, create date headers, build display_groups,
        build totals, apply sheet formatting.

        Args:

        Returns:

        """
        self._create_xlInstance()
        summary = self.wb.sheets["Template"]
        summary.activate()

        ##Update underlying data
        self._update_data()

        ##Edit title
        summary.range("B2").value = (
            summary.range("B2")
            .value.replace("MinDate", self.min_date.strftime("%m/%Y"))
            .replace("MaxDate", self.max_date.strftime("%m/%Y"))
        )

        # Loop to create date headers
        start_col = 3
        month_years = self._get_unique_months()
        for month_year in month_years:
            start_col += 1
            self._create_summary_header(summary, start_col, month_year)

        # Iterate over category groups now
        iter_row = 9
        category_groups = self._get_category_groups()
        items = self._get_items()
        for _, cg in category_groups.iterrows():
            iter_row += 2
            iter_row = self._create_category(summary, iter_row, start_col, cg, items)

        # Create totals
        iter_row += 2
        iter_row = self._build_totals(summary, iter_row, start_col)

        # Sheet-level formatting
        self._sheet_level_formatting(summary, start_col, iter_row)

    def save_and_close(self):
        """Using instance of xlwings.Book, saves & closes file

        Parameters
        ----------
        None

        Returns
        -------
        None

        """
        self._wb.save(
            os.path.join(
                SAVE_PATH, f"Budget Tool {datetime.now().strftime('%Y%m%d')}.xlsx"
            )
        )
        self._wb.close()
        self._xlApp.kill()
