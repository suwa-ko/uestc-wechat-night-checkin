const assert=require('node:assert/strict');
const {decide,timeAllowed}=require('./policy.cjs');
const day='2026-10-24';
const base={businessDate:day,recordStatus:'PENDING',hasTicket:true,locationActive:true,mapMatches:true,hasSubmit:true,authRequired:false};
assert.equal(decide(base,day,day+' 21:01:00'),'READY');
for(const time of ['20:59:59','21:00:59','23:00:00','00:01:00'])assert.equal(timeAllowed(day+' '+time),false);
for(const time of ['21:01:00','22:59:59'])assert.equal(timeAllowed(day+' '+time),true);
for(const [change,verdict] of [
 [{businessDate:'2026-10-23'},'BUSINESS_DATE_MISMATCH'],
 [{recordStatus:'CHECKED_IN'},'ALREADY_DONE'],
 [{recordStatus:'EXEMPT'},'EXEMPT'],
 [{recordStatus:'STUDENT_REPORTED'},'EXISTING_CASE_RECORD'],
 [{recordStatus:'INSTRUCTOR_REPORTED'},'EXISTING_CASE_RECORD'],
 [{recordStatus:'UNRECOGNIZED'},'UNKNOWN_RECORD_STATUS'],
 [{abnormalFlag:true},'ADVISER_REQUIRED'],
 [{statusReadCode:'401'},'STATUS_READ_FAILED'],
 [{hasTicket:false},'TICKET_MISSING'],
 [{locationActive:false},'LOCATION_NOT_READY'],
 [{mapMatches:false},'LOCATION_NOT_READY'],
 [{hasSubmit:false},'SUBMIT_BUTTON_UNAVAILABLE'],
 [{authRequired:true},'AUTH_REQUIRED'],
])assert.equal(decide({...base,...change},day,day+' 21:01:00'),verdict);
console.log('Policy guards passed: time, business date, existing record, authentication and location.');
