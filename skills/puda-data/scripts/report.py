"""
puda-data Report Generator

Generate markdown reports with pluggable visualizations.
"""

from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Callable, Any, Optional, Dict

from extractor import extract_measurement_data, get_run_info, get_protocol
from hasher import generate_fingerprint
from plotter import plot_measurement, get_data_summary
from config import get_report_dir


DEFAULT_REPORT_DIR = get_report_dir()


class ExperimentReport:
    """
    Markdown report builder with pluggable visualizations.

    The report always includes:
    - Run metadata (ID, protocol, timestamps)
    - Data integrity hashes (measurement_hash, run_hash, checksum)
    - Data summary (points, ranges)

    Users can add custom:
    - Plots (any visualization function)
    - Tables (data summaries)
    - Markdown (notes, comments)
    """

    def __init__(
        self,
        run_id: str,
        command_name: str = "CV",
        title: str = None
    ):
        """
        Initialize report.

        Args:
            run_id: The run identifier
            command_name: Measurement type (CV, OCV, etc.)
            title: Report title (auto-generated if None)
        """
        self.run_id = run_id
        self.command_name = command_name
        self.title = title or f"Experiment Report - {command_name}"
        self.sections = []
        self.plots = []

    def add_metadata(self) -> 'ExperimentReport':
        """Add run and protocol metadata."""
        run_info = get_run_info(self.run_id)
        protocol_id = run_info.get("protocol_id")
        protocol = get_protocol(protocol_id) if protocol_id else {}

        # Get commands
        commands = run_info.get("commands", [])
        command_names = [c['name'] for c in commands]

        section = f"""## Run Information

- **Run ID**: {self.run_id}
- **Protocol ID**: {protocol_id or 'N/A'}
- **Command**: {self.command_name}
- **Created**: {run_info.get('created_at', 'N/A')}
- **Total Commands**: {len(commands)}
- **Command Sequence**: {', '.join(command_names[:5])}{'...' if len(command_names) > 5 else ''}
"""
        if protocol:
            section += f"- **User**: {protocol.get('username', 'N/A')}\n"
            section += f"- **Description**: {protocol.get('description', 'N/A')}\n"

        self.sections.append(("metadata", section))
        return self

    def add_hashes(self) -> 'ExperimentReport':
        """Add data integrity hashes."""
        fp = generate_fingerprint(self.run_id, self.command_name)

        section = f"""## Data Integrity

| Hash Type | Value |
|-----------|-------|
| Measurement Hash | `{fp.get('measurement_hash', 'N/A')}` |
| Run Hash | `{fp.get('run_hash', 'N/A')}` |
| Checksum | `{fp.get('checksum', 'N/A')}` |
"""
        self.sections.append(("hashes", section))
        return self

    def add_summary(self) -> 'ExperimentReport':
        """Add data summary."""
        df = extract_measurement_data(self.run_id, self.command_name)
        fp = generate_fingerprint(self.run_id, self.command_name)

        if df.empty:
            self.sections.append(("summary", "## Data Summary\n\nNo data available."))
            return self

        x_col = fp.get("x_column", "col_0")
        y_col = fp.get("y_column", "col_1")
        x_range = fp.get("x_range", [0, 0])
        y_range = fp.get("y_range", [0, 0])

        section = f"""## Data Summary

| Metric | Value |
|--------|-------|
| Data Points | {len(df)} |
| {x_col} Range | [{x_range[0]:.3f}, {x_range[1]:.3f}] |
| {y_col} Range | [{y_range[0]:.2e}, {y_range[1]:.2e}] |
"""
        self.sections.append(("summary", section))
        return self

    def add_plot(
        self,
        title: str,
        plot_function: Callable,
        plot_kwargs: dict = None,
        output_subdir: str = "plots"
    ) -> 'ExperimentReport':
        """
        Add a plot to the report.

        Args:
            title: Section title for the plot
            plot_function: Function that generates and saves a plot
            plot_kwargs: Keyword arguments for the plot function
            output_subdir: Subdirectory for plots

        Returns:
            Self for chaining
        """
        plot_kwargs = plot_kwargs or {}

        # Generate plot
        plot_path = plot_function(**plot_kwargs)

        # Store relative path for markdown
        rel_path = f"{output_subdir}/{Path(plot_path).name}"

        self.plots.append((title, rel_path))

        section = f"""### {title}

![{title}]({rel_path})
"""
        self.sections.append(("plot", section))
        return self

    def add_table(self, title: str, data: Dict[str, Any]) -> 'ExperimentReport':
        """
        Add a data table.

        Args:
            title: Section title
            data: Dictionary of key-value pairs

        Returns:
            Self for chaining
        """
        lines = [f"## {title}\n", "| Key | Value |", "|-----|-------|"]
        for k, v in data.items():
            lines.append(f"| {k} | {v} |")

        section = "\n".join(lines) + "\n"
        self.sections.append(("table", section))
        return self

    def add_markdown(self, content: str) -> 'ExperimentReport':
        """
        Add raw markdown content.

        Args:
            content: Markdown content

        Returns:
            Self for chaining
        """
        self.sections.append(("custom", content))
        return self

    def build(self) -> str:
        """
        Build the complete report markdown.

        Returns:
            Complete markdown string
        """
        lines = [
            f"# {self.title}",
            "",
            f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
        ]

        # Add sections in order
        for section_type, content in self.sections:
            lines.append(content)

        # Add plots section at the end
        if self.plots:
            lines.append("## Visualizations\n")
            for title, path in self.plots:
                lines.append(f"### {title}")
                lines.append(f"![{title}]({path})")
                lines.append("")

        return "\n".join(lines)

    def save(self, output_path: str = None) -> str:
        """
        Save report to file.

        Args:
            output_path: Output file path (auto-generated if None)

        Returns:
            Path to saved report
        """
        # Generate default path if not provided
        if output_path is None:
            DEFAULT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = DEFAULT_REPORT_DIR / f"report_{self.run_id[:8]}_{timestamp}.md"

        # Ensure directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Build and save
        content = self.build()
        with open(output_path, 'w') as f:
            f.write(content)

        print(f"Report saved: {output_path}")
        return str(output_path)


def generate_report(
    run_id: str,
    output_dir: str = None,
    include_plot: bool = True,
    command_name: str = "CV"
) -> str:
    """
    Generate a complete report with one call.

    Args:
        run_id: The run identifier
        output_dir: Output directory
        include_plot: Whether to include a CV plot
        command_name: Measurement type

    Returns:
        Path to saved report
    """
    report = ExperimentReport(run_id, command_name)

    # Add standard sections
    report.add_metadata()
    report.add_hashes()
    report.add_summary()

    # Add plot if requested
    if include_plot:
        report.add_plot(
            title=f"{command_name} Curve",
            plot_function=plot_measurement,
            plot_kwargs={"run_id": run_id, "command": command_name}
        )

    # Generate output path
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"report_{run_id[:8]}_{timestamp}.md"
    else:
        output_path = None

    return report.save(str(output_path) if output_path else None)
