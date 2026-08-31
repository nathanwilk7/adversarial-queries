SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((movie_companies CROSS JOIN (title CROSS JOIN cast_info)) CROSS JOIN company_name) CROSS JOIN info_type) CROSS JOIN movie_info_idx) CROSS JOIN char_name) CROSS JOIN person_info
WHERE char_name.surname_pcode = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info_idx.info_type_id = info_type.id
  AND movie_info_idx.movie_id = title.id
  AND person_info.info_type_id = info_type.id;
