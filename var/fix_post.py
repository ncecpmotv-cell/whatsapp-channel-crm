import sqlite3, time
c = sqlite3.connect('/var/crm/preview.db')
c.execute("update crm_posts set status='published', published_at=?, message_id=?, last_error=NULL "
          "where id='2c02bbe8f692'", (int(time.time()), '3EB0AAD40FD6484302174F'))
c.execute("update outbox set status='done', last_error=NULL where ref='2c02bbe8f692'")
c.commit()
print('fixed')
