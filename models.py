from typing import List, Optional, Union
from pydantic import BaseModel, HttpUrl


class Contact(BaseModel):
    Name: str
    Office: str
    Phone: str
    Email: str


class RegulationNumber(BaseModel):
    text: Optional[str] = None
    url: Optional[HttpUrl] = None


class ProductCode(BaseModel):
    code: str
    footnote_number: Optional[str] = None
    url: Optional[HttpUrl] = None


class CFRProcodeEntry(BaseModel):
    Regulation_Number: Optional[RegulationNumber] = None
    Device_Name: str
    Device_Class: str
    Product_Code: ProductCode


class StandardsDevelopmentOrganization(BaseModel):
    Acronym: Optional[str] = None
    Name: Optional[str] = None
    Website: Optional[HttpUrl] = None


class FdaStandard(BaseModel):
    url: HttpUrl
    standard_identification_no: int
    FR_Recognition_List_Number: Optional[str] = None
    Date_of_Entry: Optional[str] = None
    FR_Recognition_Number: Optional[str] = None
    Standard: Optional[str] = None
    Scope_Abstract: Optional[str] = None
    Extent_of_Recognition: Optional[str] = None
    Rationale_for_Recognition: Optional[str] = None
    Transition_Period: Optional[str] = None
    FDA_Technical_Contacts: Optional[List[Contact]] = None
    Standards_Development_Organization: Optional[StandardsDevelopmentOrganization] = None
    FDA_Specialty_Task_Group: Optional[str] = None
    FDA_Guidance_Publications: Optional[List[str]] = None
    Public_Law_CFR_Procode: Optional[Union[str, List[CFRProcodeEntry]]] = None
