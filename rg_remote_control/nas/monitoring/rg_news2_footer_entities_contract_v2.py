#!/usr/bin/env python3
"""NEWS2 Telegram native caption entities footer, no IO or network.

This module is staged, not linked into the production Telegram publisher
until live package compatibility has been verified.
"""
import json
import re

URL='https://links.rginfoua.pp.ua/'
LABEL='УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ "РАША ГУДБАЙ"'
class FooterContractError(ValueError):pass

def length16(s):
    return len(s.encode('utf-16-le'))//2

def append_footer(body,limit=1024):
    if not isinstance(body,str):raise FooterContractError('BODY_TYPE')
    if type(limit)!=int or limit not in (1024,4096):
        raise FooterContractError('LIMIT')
    body=body.strip()
    if not body:raise FooterContractError('EMPTY_BODY')
    if LABEL in body or URL in body:
        raise FooterContractError('FOOTER_ALREADY_PRESENT_OR_URL_DUPLICATE')
    # Reserve UTF-16 code units before finalizing the Telegram message.
    prefix=body+'\n\n'
    caption=prefix+LABEL
    if length16(caption)>limit:raise FooterContractError('CAPTION_LIMIT_EXCEEDED')
    offset=length16(prefix)
    n=length16(LABEL)
    ents=[
        {'type':'bold','offset':offset,'length':n},
        {'type':'text_link','offset':offset,'length':n,'url':URL},
    ]
    return caption,ents

def validate_footer(text,entities,limit=1024):
    if not isinstance(text,str) or not text.endswith('\n\n'+LABEL):
        raise FooterContractError('LABEL_MISSING_OR_NOT_LAST')
    if length16(text)>limit:raise FooterContractError('CAPTION_LIMIT_EXCEEDED')
    if text.count(LABEL)!=1:raise FooterContractError('LABEL_DUPLICATED')
    offset=length16(text)-length16(LABEL)
    expected=[{'type':'bold','offset':offset,'length':length16(LABEL)},
              {'type':'text_link','offset':offset,'length':length16(LABEL),'url':URL}]
    if entities!=expected:raise FooterContractError('TELEGRAM_ENTITIES_DIFFER')
    return True

def selftest():
    a,e=append_footer('💥 Новина з України')
    assert validate_footer(a,e)
    assert e[0]['offset']==length16('💥 Новина з України\n\n')
    assert e[0]['offset']>len('💥 Новина з України\n\n')
    assert validate_footer(*append_footer('Новина',4096),4096)
    for bad in ('','Новина '+LABEL,'Новина '+URL):
        try:append_footer(bad)
        except FooterContractError:pass
        else:raise AssertionError('FOOTER_REJECT_FAILED')
    try:append_footer('📣'*550)
    except FooterContractError:pass
    else:raise AssertionError('UTF16_CAPTION_LIMIT_NOT_ENFORCED')
    print('NEWS2_TELEGRAM_FOOTER_ENTITIES_7_CASES_PASS')
    print('NEWS2_UTF16_BOLD_CLICKABLE_FOOTER_PASS')

if __name__=='__main__':
    selftest()
