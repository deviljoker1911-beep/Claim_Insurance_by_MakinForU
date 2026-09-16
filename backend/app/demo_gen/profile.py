"""Single source of truth for the synthetic demo claim. All values are fictional."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

NOTICE = "SYNTHETIC DEMO DOCUMENT — NOT A REAL RECORD"


@dataclass(frozen=True)
class Patient:
    name: str = "Rajesh Sharma"
    name_on_pharmacy_bill: str = "Rajesh K."  # seeded issue: patient-name mismatch
    name_on_card: str = "RAJESH SHARMA"
    age: int = 46
    sex: str = "Male"
    dob: str = "14-03-1979"
    uhid: str = "UHID-123456"
    ipd_no: str = "IPD/2026/004512"
    address: str = "Flat 12B, Demo Residency, Sector 9, Demo City - 110099"
    phone: str = "+91 9XXXX X4521 (masked)"
    next_of_kin: str = "Sunita Sharma (Wife)"
    blood_group: str = "B Positive"
    weight: str = "72 kg"
    height: str = "170 cm"

    @property
    def age_sex(self) -> str:
        return f"{self.age} Y / {self.sex}"


@dataclass(frozen=True)
class Hospital:
    name: str = "CityCare Multispeciality Hospital"
    address: str = "Plot 21, Health Avenue, Demo City - 110099"
    phone: str = "Tel: +91-00-0000-0000 (demo)"
    email: str = "care@citycare.example"
    registration: str = "Hospital Reg. No.: DEMO/HOSP/0451"
    pharmacy_licence: str = "Drug Licence No.: DEMO/DL/0451"


@dataclass(frozen=True)
class Cover:
    insurer: str = "Demo Health Insurance"
    tpa: str = "Demo TPA"
    policy_no: str = "DHI/POL/2026/778812"
    member_id: str = "DTPA-MEM-0099812"
    sum_insured: str = "5,00,000.00"
    valid_from: str = "01-04-2025"
    valid_to: str = "31-03-2026"


@dataclass(frozen=True)
class Stay:
    admission: date = date(2026, 1, 12)
    admission_time: str = "09:40"
    surgery: date = date(2026, 1, 13)
    discharge: date = date(2026, 1, 16)
    discharge_time: str = "11:30"
    ward: str = "Surgical Ward - Room 304 (Twin Sharing)"
    follow_up: date = date(2026, 1, 23)

    @property
    def room_days(self) -> int:
        return (self.discharge - self.admission).days


@dataclass(frozen=True)
class Clinical:
    diagnosis: str = "Acute cholecystitis"
    icd10: str = "K81.0"
    procedure: str = "Laparoscopic Cholecystectomy"
    procedure_short: str = "Lap Chole"
    procedure_abbrev: str = "Lap. Cholecystectomy"
    anaesthesia: str = "General anaesthesia"
    surgeon: str = "Dr. Anil Mehta"
    surgeon_qualification: str = "MS (General Surgery)"
    surgeon_registration: str = "Reg. No. DEMO-MC-20417"
    assistant_surgeon: str = "Dr. Rohan Das"
    resident: str = "Dr. Kunal Joshi"
    anaesthetist: str = "Dr. Priya Nair"
    anaesthetist_qualification: str = "MD (Anaesthesiology)"
    anaesthetist_registration: str = "Reg. No. DEMO-MC-31882"
    radiologist: str = "Dr. Neha Kulkarni, MD (Radiodiagnosis)"
    pathologist: str = "Dr. Arjun Batra, MD (Pathology)"
    primary_nurse: str = "Sr. Mary Thomas, RN"
    nursing_supervisor: str = "Sr. Grace D'Souza"
    scrub_nurse: str = "Sr. Leena Pillai"

    @property
    def surgeon_full(self) -> str:
        return f"{self.surgeon}, {self.surgeon_qualification}"

    @property
    def anaesthetist_full(self) -> str:
        return f"{self.anaesthetist}, {self.anaesthetist_qualification}"


@dataclass(frozen=True)
class BillLine:
    description: str
    qty: int
    rate: Decimal
    amount: Decimal  # printed amount; may intentionally differ from qty x rate

    @property
    def expected_amount(self) -> Decimal:
        return self.rate * self.qty


@dataclass(frozen=True)
class PharmacyLine(BillLine):
    batch: str = ""
    expiry: str = ""


def _d(value: str) -> Decimal:
    return Decimal(value)


MAIN_BILL_NO = "CCH/IP/2026/08812"
OT_BILL_NO = MAIN_BILL_NO  # seeded issue: duplicate bill number
PHARMACY_BILL_NO = "PH/2026/11873"
IMPLANT_INVOICE_NO = "DS/INV/2026/0391"

MAIN_BILL_LINES = (
    # Seeded issue: 4 x 4,500.00 is printed as 20,000.00 (should be 18,000.00).
    BillLine("Room Rent - Twin Sharing (12-01-2026 to 16-01-2026)", 4, _d("4500.00"), _d("20000.00")),
    BillLine("Nursing Charges", 4, _d("1200.00"), _d("4800.00")),
    BillLine("Consultation - Dr. Anil Mehta", 3, _d("800.00"), _d("2400.00")),
    BillLine("Surgeon Fee - Laparoscopic Cholecystectomy", 1, _d("35000.00"), _d("35000.00")),
    BillLine("Anaesthetist Fee", 1, _d("10500.00"), _d("10500.00")),
    BillLine("Operation Theatre Charges (as per OT bill)", 1, _d("18000.00"), _d("18000.00")),
    BillLine(f"Pharmacy & Consumables (as per bill {PHARMACY_BILL_NO})", 1, _d("9860.00"), _d("9860.00")),
    BillLine(f"Implants (as per invoice {IMPLANT_INVOICE_NO})", 1, _d("6600.00"), _d("6600.00")),
    BillLine("Laboratory & Radiology Investigations", 1, _d("5400.00"), _d("5400.00")),
    BillLine("Diet Charges", 4, _d("450.00"), _d("1800.00")),
)

OT_BILL_LINES = (
    BillLine("Operation Theatre Charges (Laparoscopic Suite)", 1, _d("9500.00"), _d("9500.00")),
    BillLine("Laparoscopy Equipment Charges", 1, _d("4500.00"), _d("4500.00")),
    BillLine("Anaesthesia Workstation & Monitoring", 1, _d("2500.00"), _d("2500.00")),
    BillLine("OT Consumables & Sterilisation", 1, _d("1500.00"), _d("1500.00")),
)

PHARMACY_LINES = (
    PharmacyLine("Inj. Ceftriaxone 1 g", 6, _d("85.00"), _d("510.00"), "CFX2511A", "08/2027"),
    PharmacyLine("Inj. Metronidazole 500 mg / 100 ml", 6, _d("45.00"), _d("270.00"), "MTZ2509C", "06/2027"),
    PharmacyLine("Inj. Pantoprazole 40 mg", 5, _d("62.00"), _d("310.00"), "PAN2512B", "11/2027"),
    PharmacyLine("Inj. Paracetamol 1 g / 100 ml", 6, _d("150.00"), _d("900.00"), "PCM2510D", "09/2027"),
    PharmacyLine("Inj. Ondansetron 4 mg", 4, _d("22.00"), _d("88.00"), "OND2508A", "07/2027"),
    PharmacyLine("Inj. Tramadol 50 mg", 4, _d("48.00"), _d("192.00"), "TRM2511B", "10/2027"),
    PharmacyLine("Inj. Enoxaparin 40 mg", 2, _d("377.00"), _d("754.00"), "ENX2507F", "05/2027"),
    PharmacyLine("IV Fluid Ringer Lactate 500 ml", 8, _d("55.00"), _d("440.00"), "RL25120A", "12/2027"),
    PharmacyLine("IV Fluid Dextrose Normal Saline 500 ml", 6, _d("52.00"), _d("312.00"), "DNS2511E", "11/2027"),
    PharmacyLine("Tab. Paracetamol 650 mg", 15, _d("2.60"), _d("39.00"), "P6502512", "12/2028"),
    PharmacyLine("Cap. Omeprazole 20 mg", 10, _d("4.50"), _d("45.00"), "OMZ2509K", "09/2028"),
    PharmacyLine("Sterile Dressing Kit", 4, _d("100.00"), _d("400.00"), "SDK2510M", "10/2028"),
    PharmacyLine("Surgical Consumables Kit (Laparoscopic)", 1, _d("5600.00"), _d("5600.00"), "LSK2512P", "12/2028"),
)


@dataclass(frozen=True)
class Implant:
    item: str = "Hem-o-lok Polymer Ligating Clips (ML)"
    lot: str = "HL-44710"
    ref: str = "DEMO-ML-06"
    expiry: str = "10/2028"
    qty: int = 6
    rate: Decimal = _d("1100.00")
    concealed_rate: Decimal = _d("1000.00")  # seeded issue: overwritten value hidden under a white box
    vendor: str = "Demo Surgicals Pvt. Ltd."
    vendor_address: str = "Unit 7, Industrial Estate, Demo City - 110045"
    vendor_phone: str = "Tel: +91-00-0000-0001 (demo)"
    vendor_email: str = "orders@demosurgicals.example"
    vendor_registration: str = "Tax Reg. No.: DEMO-TAX-7781"
    purchase_order: str = "CCH/PO/2026/1177"

    @property
    def amount(self) -> Decimal:
        return self.rate * self.qty


PATIENT = Patient()
HOSPITAL = Hospital()
COVER = Cover()
STAY = Stay()
CLINICAL = Clinical()
IMPLANT = Implant()


def claim_template() -> dict:
    """Values for the New Claim form ("Fill demo claim details")."""
    return {
        "patient_name": PATIENT.name,
        "uhid": PATIENT.uhid,
        "hospital": HOSPITAL.name,
        "insurer": COVER.insurer,
        "tpa": COVER.tpa,
        "admission_date": STAY.admission,
        "discharge_date": STAY.discharge,
    }


# --- Formatting --------------------------------------------------------------------------


def dmy(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def dmy_slash(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def inr(amount: Decimal | int) -> str:
    """Indian digit grouping: 114360 -> '1,14,360.00'."""
    value = Decimal(amount).quantize(Decimal("0.01"))
    sign = "-" if value < 0 else ""
    whole, fraction = f"{abs(value):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{sign}{whole}.{fraction}"


_ONES = (
    "Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen Fifteen "
    "Sixteen Seventeen Eighteen Nineteen"
).split()
_TENS = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()


def _below_thousand(n: int) -> str:
    words = []
    if n >= 100:
        words += [_ONES[n // 100], "Hundred"]
        n %= 100
    if n >= 20:
        words.append(_TENS[n // 10])
        n %= 10
    if n:
        words.append(_ONES[n])
    return " ".join(words)


def rupees_in_words(amount: Decimal | int) -> str:
    """Whole rupees in the Indian numbering system, e.g. 'Rupees One Lakh ... Only'."""
    n = int(Decimal(amount))
    if n == 0:
        return "Rupees Zero Only"
    parts = []
    for size, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand")):
        if n >= size:
            parts.append(f"{_below_thousand(n // size)} {name}")
            n %= size
    if n:
        parts.append(_below_thousand(n))
    return f"Rupees {' '.join(parts)} Only"


def bill_total(lines) -> Decimal:
    return sum((line.amount for line in lines), Decimal("0"))
