#!/usr/bin/env python3
"""RG NEWS2 poll editorial gate. Pure validation only; never authorizes publishing."""
import re,hashlib,json,unicodedata

DANGLING=re.compile(r'(?iu)(?:^|\W)(?:і|й|та|або|чи|але|в|у|на|про|для|під|над|через|щодо|від|до|з|із|зі|без|як|коли|тому|що|які|який|яка|яке|після|перед)\s*$')
URL=re.compile(r'(?iu)(?:https?://|\bt\.me/|@[a-z0-9_]{4,}|www\.)')
NEWSY=re.compile(r'(?iu)\b(?:повідомляє|заявив|заявила|знищено|атакува\w*|вибухи|загинуло|постраждало|відбулося|обстріл|уражено)\b')
REPEATED=re.compile(r'(?iu)\b(\w{4,})\s+\1\b')
BANK=(
 ('Які новини ви хочете бачити в нашому каналі насамперед?',('Події на фронті','Міжнародна допомога Україні','Санкції та економіка росії','Події всередині росії')),
 ('Що найбільше допомагає вам перевіряти новини?',('Офіційні документи','Підтвердження з кількох джерел','Фото та відеодокази','Посилання на першоджерело')),
 ('Який формат новин вам найбільш зручний?',('Короткі повідомлення','Відео з поясненнями','Підсумок дня','Розбір ключових подій')),
 ('Яка міжнародна тема для вас зараз найцікавіша?',('Підтримка України','Санкції проти росії','Рішення міжнародних союзників','Переговори та дипломатія')),
 ('Що для вас найважливіше у щоденному огляді новин?',('Точність фактів','Швидкість повідомлень','Пояснення контексту','Підтвердження джерелами')),
 ('Який матеріал ви найчастіше дивитеся до кінця?',('Коротке відео з фактами','Повний аналіз події','Інтерв’ю зі свідками','Детальну новинну добірку')),
 ('Які дані найкраще пояснюють наслідки новини?',('Коментарі фахівців','Офіційна статистика','Інтерактивні мапи','Порівняння з попередніми подіями'))
)

def clean(s):
 if not isinstance(s,str):raise ValueError('POLL_FIELD_NOT_STRING')
 if s!=s.strip() or '\n' in s or '\r' in s or '\x00' in s or re.search(r'\s{2,}',s):
  raise ValueError('POLL_FIELD_WHITESPACE')
 if any(unicodedata.category(c).startswith('C') for c in s):raise ValueError('POLL_FIELD_CONTROL')
 return s

def validate(question,options):
 q=clean(question)
 if not 20<=len(q)<=180 or not q.endswith('?') or q.count('?')!=1:
  raise ValueError('POLL_QUESTION_INCOMPLETE')
 if URL.search(q) or REPEATED.search(q):raise ValueError('POLL_QUESTION_UNSAFE')
 if not isinstance(options,(tuple,list)) or len(options)!=4:
  raise ValueError('POLL_OPTIONS_MUST_HAVE_FOUR')
 output=[];seen=set()
 for raw in options:
  o=clean(raw)
  if not 4<=len(o)<=65:raise ValueError('POLL_OPTION_LENGTH')
  if o[-1] in ',:;.!?—–-' or o.endswith(('...','…')):
   raise ValueError('POLL_OPTION_BAD_END')
  if DANGLING.search(o) or URL.search(o) or REPEATED.search(o):
   raise ValueError('POLL_OPTION_INCOMPLETE')
  if NEWSY.search(o):raise ValueError('POLL_OPTION_LOOKS_LIKE_HEADLINE')
  norm=''.join(c for c in unicodedata.normalize('NFKC',o.casefold()) if c.isalnum())
  if norm in seen:raise ValueError('POLL_OPTION_DUPLICATE')
  seen.add(norm);output.append(o)
 body=json.dumps([q,output],ensure_ascii=False,separators=(',',':'))
 return {'question':q,'options':output,'content_sha256':hashlib.sha256(body.encode()).hexdigest(),
  'editorial_review_required':True,'publication_authorized':False}

def bank(day):
 if type(day)!=int or not 0<=day<=6:raise ValueError('POLL_DAY_INVALID')
 return validate(*BANK[day])

def selftest():
 for d in range(7):bank(d)
 bad=[
  ['Оборона України','Санкції проти росії','Переговори про','Допомога Україні'],
  ['Оборона України','Санкції проти росії','Росія атакувала Україну','Допомога Україні'],
  ['Оборона України','Санкції проти росії','Санкції проти росії','Допомога Україні']
 ]
 for options in bad:
  try:validate('Яка тема вам здається найважливішою сьогодні?',options)
  except ValueError:pass
  else:raise AssertionError('BAD_POLL_ACCEPTED')
 print('RG_POLL_QUALITY_V1_OFFLINE_PASS 7_VALID 3_REJECTED TELEGRAM_CALLS_0')
if __name__=='__main__':selftest()
