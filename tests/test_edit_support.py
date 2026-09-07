import xml.etree.ElementTree as ET
from types import SimpleNamespace
import pytest
from hwpctl.edit_support import compact_formatting_xml, set_edit_marks
from hwpctl.errors import UsageError, HangulCommandError
from hwpctl.parser import parse_args
from hwpctl.cli import _kwargs_for

class Props:
    def __init__(self, flags): self.flags=flags
    def Item(self, key): assert key=='OptionFlag'; return self.flags
    def SetItem(self, key, value): assert key=='OptionFlag'; self.flags=value

def test_marks_idempotent_preserves_other_bits():
    com=SimpleNamespace(ViewProperties=Props(24))
    assert set_edit_marks(com,control_marks=True,paragraph_marks=True)['after_flags']==30
    assert not set_edit_marks(com,control_marks=True,paragraph_marks=True)['changed']
    assert set_edit_marks(com,control_marks=False,paragraph_marks=False)['after_flags']==24

@pytest.mark.parametrize('c,p',[(1,True),(True,False),(None,True)])
def test_marks_reject_ambiguous_inputs(c,p):
    with pytest.raises(UsageError):set_edit_marks(None,control_marks=c,paragraph_marks=p)

def test_marks_cli():
    args=parse_args(['set_edit_marks','--no-control-marks','--no-paragraph-marks'])
    assert _kwargs_for(args)=={'control_marks':False,'paragraph_marks':False}

def fixture_parts():
    return {'Contents/header.xml':b'''<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"><hh:charProperties itemCnt="3"><hh:charPr id="0"/><hh:charPr id="1"/><hh:charPr id="2"/></hh:charProperties><hh:paraProperties itemCnt="2"><hh:paraPr id="0"/><hh:paraPr id="1"/></hh:paraProperties><hh:paraHead charPrIDRef="4294967295"/></hh:head>''',
    'Contents/section0.xml':b'''<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p paraPrIDRef="0" pageBreak="1"><hp:run charPrIDRef="2"><hp:rect id="7"/><hp:t>Keep this</hp:t></hp:run></hp:p><hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"/></hp:p></hs:sec>'''}

def test_compact_preserves_anchors_empty_paragraphs_and_text():
    parts=fixture_parts(); result,report=compact_formatting_xml(parts)
    assert report['removed_character_formats']==1
    assert report['removed_paragraph_formats']==1
    assert report['removed_paragraphs']==0 and report['preserved_paragraphs']==2
    root=ET.fromstring(result['Contents/section0.xml'])
    assert len(root)==2 and root[0].get('pageBreak')=='1'
    assert root[0][0].get('charPrIDRef')=='1'
    assert root[0][0][0].get('id')=='7'
    assert ''.join(root.itertext())=='Keep this'
    second,again=compact_formatting_xml(result)
    assert second==result and not again['changed_parts']
    assert parts==fixture_parts()

def test_compact_rejects_dangling_ref():
    parts=fixture_parts();parts['Contents/section0.xml']=parts['Contents/section0.xml'].replace(b'charPrIDRef="2"',b'charPrIDRef="88"')
    with pytest.raises(UsageError):compact_formatting_xml(parts)

def test_compact_rejects_dtd():
    parts=fixture_parts();parts['Contents/section0.xml']=b'<!DOCTYPE x><x/>'
    with pytest.raises(UsageError):compact_formatting_xml(parts)

def test_compact_keeps_formats_referenced_by_styles():
    parts=fixture_parts();parts['Contents/header.xml']=parts['Contents/header.xml'].replace(b'</hh:head>',b'<hh:style charPrIDRef="1" paraPrIDRef="1"/></hh:head>')
    _,report=compact_formatting_xml(parts)
    assert report['removed_character_formats']==report['removed_paragraph_formats']==0
