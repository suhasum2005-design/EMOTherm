import base64
import hashlib
import io
import json
from datetime import datetime, timezone

from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

from blockchain.chain import canonical


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def signed_certificate(payload, vault):
    encoded = canonical(payload)
    return {
        **payload,
        'signature': {
            'algorithm': 'RSA-PSS-SHA256',
            'signed_payload_sha256': sha256(encoded),
            'public_key_fingerprint': vault.public_key_fingerprint(),
            'value': base64.b64encode(vault.sign(encoded)).decode()
        }
    }


def verify_signed_certificate(document, vault):
    if not isinstance(document, dict) or not isinstance(document.get('signature'), dict):
        return False, False, 'Certificate signature is missing'
    signature = document['signature']
    payload = {k: v for k, v in document.items() if k != 'signature'}
    encoded = canonical(payload)
    hash_valid = signature.get('signed_payload_sha256') == sha256(encoded)
    try:
        raw_signature = base64.b64decode(signature.get('value', ''), validate=True)
    except Exception:
        return False, hash_valid, 'Certificate signature is malformed'
    signature_valid = (
        signature.get('algorithm') == 'RSA-PSS-SHA256'
        and signature.get('public_key_fingerprint') == vault.public_key_fingerprint()
        and vault.verify_signature(encoded, raw_signature)
    )
    return signature_valid, hash_valid, '' if signature_valid and hash_valid else 'Signature or report hash does not match'


def qr_drawing(value, size=34*mm):
    widget = qr.QrCodeWidget(value)
    x1, y1, x2, y2 = widget.getBounds()
    scale = size / max(x2-x1, y2-y1)
    drawing = Drawing(size, size, transform=[scale, 0, 0, scale, 0, 0])
    drawing.add(widget)
    return drawing


def certificate_pdf(document, verify_url):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=16*mm, bottomMargin=16*mm,
                            title='EmoTherm SecureChain Verification Certificate')
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CertificateTitle', parent=styles['Title'], fontName='Helvetica-Bold',
                              fontSize=20, leading=24, textColor=colors.HexColor('#12313a'), alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='Section', parent=styles['Heading2'], fontName='Helvetica-Bold',
                              fontSize=11, leading=14, textColor=colors.HexColor('#168f7a'), spaceBefore=10, spaceAfter=5))
    styles.add(ParagraphStyle(name='Small', parent=styles['BodyText'], fontSize=7.5, leading=10, textColor=colors.HexColor('#516970')))
    styles.add(ParagraphStyle(name='Status', parent=styles['Heading2'], fontSize=12, leading=15,
                              textColor=colors.HexColor('#087f68'), alignment=TA_CENTER))
    scan, prediction, integrity, signature = document['scan'], document['prediction'], document['integrity'], document['signature']
    story = [Paragraph('EmoTherm SecureChain', styles['CertificateTitle']),
             Paragraph('DIGITAL EVIDENCE AND VERIFICATION CERTIFICATE', styles['Status']), Spacer(1, 5*mm)]
    summary = Table([
        [Paragraph('<b>Certificate ID</b><br/>'+document['certificate_id'], styles['BodyText']),
         qr_drawing(verify_url),
         Paragraph('<b>Integrity at export</b><br/><font color="#087f68">VERIFIED</font><br/><br/><b>Issued</b><br/>'+document['issued_at'], styles['BodyText'])]
    ], colWidths=[70*mm, 40*mm, 50*mm])
    summary.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BOX',(0,0),(-1,-1),.7,colors.HexColor('#aac3c8')),
                                 ('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f0f7f5')),('PADDING',(0,0),(-1,-1),8)]))
    story += [summary, Paragraph('Scan and prediction', styles['Section'])]
    probability_rows = [['Emotion', 'Probability']] + [[k.title(), f'{v*100:.1f}%'] for k,v in prediction['probabilities'].items()]
    details = Table([
        ['Scan ID', scan['id']], ['Captured', scan['timestamp']], ['Source', scan['source']],
        ['Predicted expression', prediction['emotion'].title()], ['Model confidence', f"{prediction['confidence']*100:.1f}%"],
        ['Model version', prediction['model']]
    ], colWidths=[42*mm, 118*mm])
    details.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.35,colors.HexColor('#c4d4d7')),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#edf5f3')),
                                 ('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8.5),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),5)]))
    probs = Table(probability_rows, colWidths=[80*mm, 80*mm])
    probs.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.35,colors.HexColor('#c4d4d7')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#173840')),
                               ('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('ALIGN',(1,1),(1,-1),'RIGHT'),('FONTSIZE',(0,0),(-1,-1),8.5),('PADDING',(0,0),(-1,-1),5)]))
    story += [details, Spacer(1,4*mm), probs, Paragraph('Cryptographic proof', styles['Section'])]
    proof_rows = [
        ['Record commitment', integrity['record_sha256']], ['Original image SHA-256', integrity['image_sha256']],
        ['Model SHA-256', integrity['model_sha256']], ['Block index', str(integrity['block_index'])],
        ['Block hash', integrity['block_hash']], ['Previous block hash', integrity['previous_block_hash']],
        ['Chain integrity', 'VALID' if integrity['chain_valid'] else 'FAILED'],
        ['Record integrity', 'VALID' if integrity['record_valid'] else 'FAILED']]
    proof = Table([[Paragraph(f'<b>{a}</b>', styles['Small']), Paragraph(b, styles['Small'])] for a,b in proof_rows], colWidths=[42*mm,118*mm])
    proof.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.35,colors.HexColor('#c4d4d7')),('VALIGN',(0,0),(-1,-1),'TOP'),
                               ('BACKGROUND',(0,0),(0,-1),colors.HexColor('#edf5f3')),('PADDING',(0,0),(-1,-1),5)]))
    story += [proof, PageBreak(), Paragraph('Digital signature', styles['Section'])]
    signature_rows = [['Algorithm', signature['algorithm']], ['Signed payload SHA-256', signature['signed_payload_sha256']],
                      ['Public-key fingerprint', signature['public_key_fingerprint']], ['Signature', signature['value']]]
    sig_table = Table([[Paragraph(f'<b>{a}</b>', styles['Small']), Paragraph(b, styles['Small'])] for a,b in signature_rows], colWidths=[42*mm,118*mm])
    sig_table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.35,colors.HexColor('#c4d4d7')),('VALIGN',(0,0),(-1,-1),'TOP'),
                                   ('BACKGROUND',(0,0),(0,-1),colors.HexColor('#edf5f3')),('PADDING',(0,0),(-1,-1),5)]))
    story += [sig_table, Paragraph('Independent verification', styles['Section']),
              Paragraph('Scan the QR code or open the verification page and upload the companion JSON certificate. The verifier recomputes the canonical report hash, validates the RSA-PSS signature with this installation\'s public key, and compares the scan, model, and blockchain commitments with the stored record.', styles['BodyText']),
              Spacer(1,4*mm), Paragraph(verify_url, styles['Small']), Spacer(1,7*mm),
              Paragraph('<b>Research limitation:</b> The predicted label is a model estimate of the trained facial-expression classes. It does not establish a person\'s internal emotional state.', styles['Small'])]
    def footer(canvas, pdfdoc):
        canvas.saveState(); canvas.setFont('Helvetica', 7); canvas.setFillColor(colors.HexColor('#6d8186'))
        canvas.drawString(18*mm, 9*mm, document['certificate_id']); canvas.drawRightString(192*mm, 9*mm, f'Page {pdfdoc.page}')
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
