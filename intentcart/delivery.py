"""Validated worldwide coarse destinations. A postal code is not a tax jurisdiction."""
import re
import pycountry
from functools import lru_cache
from pydantic import Field,field_validator,model_validator
from .workspace import Strict

class Destination(Strict):
 country:str=Field(min_length=2,max_length=2)
 region:str=Field(default='',max_length=10)
 postal:str=Field(default='',max_length=20)
 test:bool=False
 @field_validator('country','region','postal',mode='before')
 @classmethod
 def canonical(cls,value):
  if not isinstance(value,str):raise ValueError('Use text for country, region and postal code.')
  return ' '.join(value.strip().upper().split())
 @model_validator(mode='after')
 def supported(self):
  if not pycountry.countries.get(alpha_2=self.country):raise ValueError('Choose a current ISO delivery country.')
  if self.region.startswith(self.country+'-'):self.region=self.region[len(self.country)+1:]
  if self.region and not pycountry.subdivisions.get(code=self.country+'-'+self.region) and not (self.country=='US' and self.region in ('AA','AE','AP')):raise ValueError('Choose a region belonging to the delivery country.')
  if self.postal and not re.fullmatch(r'[\w -]{1,20}',self.postal,re.UNICODE):raise ValueError('Use a postal code without links or punctuation.')
  if self.country=='US' and not re.fullmatch(r'\d{5}(?:-\d{4})?',self.postal):raise ValueError('Use a five-digit US ZIP, optionally with four-digit extension.')
  if self.country=='CA' and not re.fullmatch(r'[A-Z]\d[A-Z] ?\d[A-Z]\d',self.postal):raise ValueError('Use a Canadian postal code, for example M5V 2T6.')
  if self.country in ('US','CA','AU') and not self.region:raise ValueError('Select the delivery state or province.')
  return self
 def key(self):return self.country+':'+self.region+':'+self.postal
 def public(self):return self.model_dump()
 def merchant_address(self):
  country=pycountry.countries.get(alpha_2=self.country)
  region=pycountry.subdivisions.get(code=self.country+'-'+self.region) if self.region else None
  return {'country':self.country,'region':self.region,'postal':self.postal,'country_name':{'GB':'United Kingdom','US':'United States','KR':'South Korea','TW':'Taiwan'}.get(self.country,country.name),'region_name':region.name if region else self.region}

@lru_cache(maxsize=1)
def catalog():
 return {'countries':sorted([{'code':v.alpha_2,'name':v.name} for v in pycountry.countries],key=lambda v:v['name']),'regions':{c.alpha_2:sorted([{'code':v.code[len(c.alpha_2)+1:],'name':v.name} for v in pycountry.subdivisions.get(country_code=c.alpha_2) or []],key=lambda v:v['name']) for c in pycountry.countries},'scope':'ISO country/region identifiers validate input; they do not establish merchant delivery coverage or exact tax jurisdiction.'}
