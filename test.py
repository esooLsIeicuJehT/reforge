import re

content = """
.method public checkServerTrusted([Ljava/security/cert/X509Certificate;Ljava/lang/String;)V
    .annotation system Ldalvik/annotation/Throws;
        value = {
            Ljava/security/cert/CertificateException;
        }
    .end annotation

    .registers 3
    const/4 v0, 0x0
    return-void
.end method
"""

content = re.sub(
    r'(\.method public checkServerTrusted\(\[Ljava/security/cert/X509Certificate;Ljava/lang/String;\)V.*?)(?:\.locals\s+\d+|\.registers\s+\d+)',
    r'\g<0>\n    return-void',
    content, flags=re.DOTALL
)

print(content)
