SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((keyword CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN name) CROSS JOIN aka_name) CROSS JOIN movie_keyword) CROSS JOIN person_info) CROSS JOIN info_type) CROSS JOIN movie_info
WHERE aka_name.surname_pcode = ''
  AND aka_name.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
