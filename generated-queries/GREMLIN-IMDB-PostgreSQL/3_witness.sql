SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((name CROSS JOIN (title CROSS JOIN cast_info)) CROSS JOIN aka_name) CROSS JOIN keyword) CROSS JOIN char_name) CROSS JOIN movie_keyword
WHERE cast_info.note = '(as Dick O''Harry)'
  AND char_name.surname_pcode = ''
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id;
