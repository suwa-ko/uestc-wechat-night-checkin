'use strict';
function timeAllowed(now){const s=now.slice(11);return s>='21:01:00'&&s<'23:00:00';}
function decide(snapshot,day,now){
 if(!timeAllowed(now))return 'OUTSIDE_WINDOW';
 if(snapshot.authRequired)return 'AUTH_REQUIRED';
 if(snapshot.businessDate!==day)return 'BUSINESS_DATE_MISMATCH';
 if(snapshot.statusReadCode!==undefined&&snapshot.statusReadCode!=='0')return 'STATUS_READ_FAILED';
 if(snapshot.recordStatus==='CHECKED_IN')return 'ALREADY_DONE';
 if(snapshot.recordStatus==='EXEMPT')return 'EXEMPT';
 if(['STUDENT_REPORTED','INSTRUCTOR_REPORTED'].includes(snapshot.recordStatus))return 'EXISTING_CASE_RECORD';
 if(snapshot.recordStatus!=='PENDING')return 'UNKNOWN_RECORD_STATUS';
 if(snapshot.abnormalFlag)return 'ADVISER_REQUIRED';
 if(!snapshot.hasTicket)return 'TICKET_MISSING';
 if(!snapshot.locationActive||!snapshot.mapMatches)return 'LOCATION_NOT_READY';
 if(snapshot.hasSubmit!==true)return 'SUBMIT_BUTTON_UNAVAILABLE';
 return 'READY';
}
module.exports={decide,timeAllowed};
