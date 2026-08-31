SET join_collapse_limit = 1;
SELECT count(*)
FROM ((movie_keyword CROSS JOIN (title CROSS JOIN name)) CROSS JOIN cast_info) CROSS JOIN keyword
WHERE cast_info.note = '(as Dick O''Harry)'
  AND name.surname_pcode = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id;
