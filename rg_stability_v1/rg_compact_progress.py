"""Compact Studio progress widget, opt-in and Studio-owned.

Create this widget only inside the existing Qt application when integration is approved.
It reads snapshots and cannot start background processes.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar


class CompactProgressWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RGCompactProgress")
        self.setMinimumWidth(340)
        self.setStyleSheet("""
            QFrame#RGCompactProgress {background:#161C26;border:1px solid #344154;border-radius:12px;}
            QFrame#RGCompactProgress QLabel {color:#EDF3FC;border:none;background:transparent;}
            QFrame#RGCompactProgress QProgressBar {border:0;background:#303B4B;border-radius:5px;}
            QFrame#RGCompactProgress QProgressBar::chunk {background:#F23B55;border-radius:5px;}
        """)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(16,12,16,12)
        layout.setSpacing(8)
        header=QHBoxLayout()
        self.stream_label=QLabel("STREAM --")
        self.stream_label.setStyleSheet("font-size:13px;font-weight:700;")
        self.pct_label=QLabel("0.0%")
        self.pct_label.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
        self.pct_label.setStyleSheet("font-size:17px;font-weight:700;")
        header.addWidget(self.stream_label)
        header.addStretch()
        header.addWidget(self.pct_label)
        layout.addLayout(header)
        self.bar=QProgressBar()
        self.bar.setRange(0,1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        layout.addWidget(self.bar)
        self.stage=QLabel("IDLE")
        self.stage.setWordWrap(True)
        self.stage.setStyleSheet("font-size:11px;color:#AAB9CC;")
        layout.addWidget(self.stage)
        self.resources=QLabel("GPU --  |  CPU --  |  ETA --")
        self.resources.setStyleSheet("font-size:11px;color:#9EAFC4;")
        layout.addWidget(self.resources)

    def update_snapshot(self, snapshot:dict):
        pct=max(0.,min(100.,float(snapshot.get("progress_percent") or 0.)))
        self.bar.setValue(round(pct*10))
        self.pct_label.setText(f"{pct:.1f}%")
        self.stream_label.setText("STREAM "+str(snapshot.get("stream") or "--"))
        self.stage.setText(str(snapshot.get("stage") or "IDLE")[:140])
        def number(x):
            try:return f"{max(0,min(100,float(x))):.0f}%"
            except (TypeError,ValueError):return "--"
        self.resources.setText(
            "GPU "+number(snapshot.get("gpu_percent"))+"  |  CPU "+
            number(snapshot.get("cpu_percent"))+"  |  ETA "+
            str(snapshot.get("eta") or "--")[:32])
